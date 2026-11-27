// Bang Bang checkpoint graph builder, ABI 1 / CPython stable ABI 3.10+.
//
// This replaces only battle_persistence.encode's recursive scaffolding build.
// Python json.dumps remains responsible for the exact VERSION 1 JSON bytes.
// Container IDs, insertion/iteration order, aliases and supported subclass
// behavior deliberately match the Python encoder, including its unusual use
// of type(obj).__name__ as the kind of a container subclass.
#ifndef Py_LIMITED_API
#define Py_LIMITED_API 0x030A0000
#endif
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <new>
#include <unordered_map>

#ifndef BB_CHECKPOINT_SOURCE_SHA256
#define BB_CHECKPOINT_SOURCE_SHA256 "unversioned"
#endif

namespace {

// Owned references are local to a call. No Python object is retained in
// process-global/module-global C++ state, so interpreter lifetimes do not mix.
class Reference {
public:
    explicit Reference(PyObject* value = nullptr) noexcept : value_(value) {}
    ~Reference() { Py_XDECREF(value_); }
    Reference(const Reference&) = delete;
    Reference& operator=(const Reference&) = delete;
    Reference(Reference&& other) noexcept : value_(other.release()) {}
    Reference& operator=(Reference&& other) noexcept {
        if (this != &other) reset(other.release());
        return *this;
    }
    PyObject* get() const noexcept { return value_; }
    explicit operator bool() const noexcept { return value_ != nullptr; }
    PyObject* release() noexcept {
        PyObject* result = value_;
        value_ = nullptr;
        return result;
    }
    void reset(PyObject* value = nullptr) noexcept {
        PyObject* previous = value_;
        value_ = value;
        Py_XDECREF(previous);
    }
private:
    PyObject* value_;
};

PyObject* retain(PyObject* value) noexcept {
    Py_INCREF(value);
    return value;
}

class RecursionGuard {
public:
    RecursionGuard()
        : entered_(Py_EnterRecursiveCall(" while encoding a battle checkpoint") == 0) {}
    ~RecursionGuard() { if (entered_) Py_LeaveRecursiveCall(); }
    bool entered() const noexcept { return entered_; }
private:
    bool entered_;
};

bool exact_scalar(PyObject* value) noexcept {
    return value == Py_None
        || Py_TYPE(value) == &PyUnicode_Type
        || Py_TYPE(value) == &PyLong_Type
        || Py_TYPE(value) == &PyFloat_Type
        || Py_TYPE(value) == &PyBool_Type;
}

// Match Python's two-value unpacking without consuming an arbitrary iterable
// beyond the third element. Own both elements before recursive callbacks.
bool unpack_pair(PyObject* pair, Reference& key, Reference& value) {
    if (PyTuple_CheckExact(pair)) {
        const Py_ssize_t count = PyTuple_Size(pair);
        if (count == 2) {
            key.reset(retain(PyTuple_GetItem(pair, 0)));
            value.reset(retain(PyTuple_GetItem(pair, 1)));
            return true;
        }
        if (count < 2) {
            PyErr_Format(PyExc_ValueError,
                         "not enough values to unpack (expected 2, got %zd)", count);
        } else {
            PyErr_SetString(PyExc_ValueError, "too many values to unpack (expected 2)");
        }
        return false;
    }
    Reference iterator(PyObject_GetIter(pair));
    if (!iterator) return false;
    key.reset(PyIter_Next(iterator.get()));
    if (!key) {
        if (!PyErr_Occurred()) {
            PyErr_SetString(PyExc_ValueError,
                            "not enough values to unpack (expected 2, got 0)");
        }
        return false;
    }
    value.reset(PyIter_Next(iterator.get()));
    if (!value) {
        if (!PyErr_Occurred()) {
            PyErr_SetString(PyExc_ValueError,
                            "not enough values to unpack (expected 2, got 1)");
        }
        return false;
    }
    Reference extra(PyIter_Next(iterator.get()));
    if (extra) {
        PyErr_SetString(PyExc_ValueError, "too many values to unpack (expected 2)");
        return false;
    }
    return PyErr_Occurred() == nullptr;
}

class Encoder {
public:
    Encoder(PyObject* decimal_type, PyObject* shield_type, PyObject* asdict)
        : decimal_type_(decimal_type), shield_type_(shield_type), asdict_(asdict),
          nodes_(PyList_New(0)),
          dict_kind_(PyUnicode_FromString("dict")),
          list_kind_(PyUnicode_FromString("list")),
          tuple_kind_(PyUnicode_FromString("tuple")),
          set_kind_(PyUnicode_FromString("set")),
          items_name_(PyUnicode_FromString("items")),
          scalar_types_(PyTuple_Pack(5,
              reinterpret_cast<PyObject*>(Py_TYPE(Py_None)),
              reinterpret_cast<PyObject*>(&PyUnicode_Type),
              reinterpret_cast<PyObject*>(&PyLong_Type),
              reinterpret_cast<PyObject*>(&PyFloat_Type),
              reinterpret_cast<PyObject*>(&PyBool_Type))),
          container_types_(PyTuple_Pack(4,
              reinterpret_cast<PyObject*>(&PyDict_Type),
              reinterpret_cast<PyObject*>(&PyList_Type),
              reinterpret_cast<PyObject*>(&PyTuple_Type),
              reinterpret_cast<PyObject*>(&PySet_Type))) {}

    bool ready() const noexcept {
        return nodes_ && dict_kind_ && list_kind_ && tuple_kind_ && set_kind_
            && items_name_ && scalar_types_ && container_types_;
    }

    PyObject* graph(PyObject* value) {
        Reference top(item(value));
        if (!top) return nullptr;
        Reference result(PyDict_New());
        if (!result
            || PyDict_SetItemString(result.get(), "root", top.get()) < 0
            || PyDict_SetItemString(result.get(), "nodes", nodes_.get()) < 0) {
            return nullptr;
        }
        return result.release();
    }

private:
    PyObject* decimal_type_;  // Borrowed from the method's live argument tuple.
    PyObject* shield_type_;
    PyObject* asdict_;
    Reference nodes_;
    Reference dict_kind_;
    Reference list_kind_;
    Reference tuple_kind_;
    Reference set_kind_;
    Reference items_name_;
    Reference scalar_types_;
    Reference container_types_;
    // Like Python's seen[id(obj)], this owns the reference wrappers but does
    // not keep input containers alive or execute __hash__/__eq__ methods.
    // Owning wrappers also keeps unusual duplicate Shield field assignments
    // from leaving a dangling wrapper in the identity map.
    std::unordered_map<PyObject*, Reference> seen_;

    PyObject* leaf(PyObject* value) {
        return exact_scalar(value) ? retain(value) : item(value);
    }

    PyObject* items_iterator(PyObject* object) {
        Reference view(PyObject_CallMethodObjArgs(object, items_name_.get(), nullptr));
        return view ? PyObject_GetIter(view.get()) : nullptr;
    }

    PyObject* shield(PyObject* object) {
        Reference converted(PyObject_CallFunctionObjArgs(asdict_, object, nullptr));
        if (!converted) return nullptr;
        Reference iterator(items_iterator(converted.get()));
        Reference fields(PyDict_New());
        if (!iterator || !fields) return nullptr;
        while (true) {
            Reference pair(PyIter_Next(iterator.get()));
            if (!pair) {
                if (PyErr_Occurred()) return nullptr;
                break;
            }
            Reference key, value;
            if (!unpack_pair(pair.get(), key, value)) return nullptr;
            // The Python Shield branch calls item(v) even for scalar values.
            // It does not encode the field keys or register the asdict result.
            Reference encoded(item(value.get()));
            if (!encoded || PyDict_SetItem(fields.get(), key.get(), encoded.get()) < 0) {
                return nullptr;
            }
        }
        Reference result(PyDict_New());
        if (!result || PyDict_SetItemString(result.get(), "shield", fields.get()) < 0) {
            return nullptr;
        }
        return result.release();
    }

    PyObject* item(PyObject* object) {
        RecursionGuard recursion;
        if (!recursion.entered()) return nullptr;

        PyObject* kind = nullptr;
        Reference subclass_kind;
        if (Py_TYPE(object) == &PyDict_Type) kind = dict_kind_.get();
        else if (Py_TYPE(object) == &PyList_Type) kind = list_kind_.get();
        else if (Py_TYPE(object) == &PyTuple_Type) kind = tuple_kind_.get();
        else if (Py_TYPE(object) == &PySet_Type) kind = set_kind_.get();
        else {
            const int scalar = PyObject_IsInstance(object, scalar_types_.get());
            if (scalar < 0) return nullptr;
            if (scalar) return retain(object);
            const int decimal = PyObject_IsInstance(object, decimal_type_);
            if (decimal < 0) return nullptr;
            if (decimal) {
                Reference text(PyObject_Str(object));
                Reference result(PyDict_New());
                if (!text || !result
                    || PyDict_SetItemString(result.get(), "decimal", text.get()) < 0) {
                    return nullptr;
                }
                return result.release();
            }
            const int is_shield = PyObject_IsInstance(object, shield_type_);
            if (is_shield < 0) return nullptr;
            if (is_shield) return shield(object);
            const int container = PyObject_IsInstance(object, container_types_.get());
            if (container < 0) return nullptr;
            subclass_kind.reset(PyObject_GetAttrString(
                reinterpret_cast<PyObject*>(Py_TYPE(object)), "__name__"));
            if (!subclass_kind) return nullptr;
            if (!container) {
                PyErr_Format(PyExc_TypeError, "Unsupported checkpoint value %U",
                             subclass_kind.get());
                return nullptr;
            }
            kind = subclass_kind.get();
        }

        const auto found = seen_.find(object);
        if (found != seen_.end()) return retain(found->second.get());

        const Py_ssize_t index = PyList_Size(nodes_.get());
        if (index < 0) return nullptr;
        Reference number(PyLong_FromSsize_t(index));
        Reference ref(PyDict_New());
        if (!number || !ref
            || PyDict_SetItemString(ref.get(), "ref", number.get()) < 0) {
            return nullptr;
        }
        seen_.emplace(object, Reference(retain(ref.get())));
        if (PyList_Append(nodes_.get(), Py_None) < 0) return nullptr;

        Reference data(PyList_New(0));
        if (!data) return nullptr;
        const int comparison = PyUnicode_CompareWithASCIIString(kind, "dict");
        if (comparison == -1 && PyErr_Occurred()) return nullptr;
        if (comparison == 0) {
            Reference iterator(items_iterator(object));
            if (!iterator) return nullptr;
            while (true) {
                Reference pair(PyIter_Next(iterator.get()));
                if (!pair) {
                    if (PyErr_Occurred()) return nullptr;
                    break;
                }
                Reference key, value;
                if (!unpack_pair(pair.get(), key, value)) return nullptr;
                Reference encoded_key(leaf(key.get()));
                if (!encoded_key) return nullptr;
                Reference encoded_value(leaf(value.get()));
                if (!encoded_value) return nullptr;
                Reference encoded_pair(PyTuple_Pack(2, encoded_key.get(), encoded_value.get()));
                if (!encoded_pair || PyList_Append(data.get(), encoded_pair.get()) < 0) {
                    return nullptr;
                }
            }
        } else {
            // Use actual iterators, including for built-ins: this preserves
            // set order, list growth and custom subclass iteration/errors.
            Reference iterator(PyObject_GetIter(object));
            if (!iterator) return nullptr;
            while (true) {
                Reference value(PyIter_Next(iterator.get()));
                if (!value) {
                    if (PyErr_Occurred()) return nullptr;
                    break;
                }
                Reference encoded(leaf(value.get()));
                if (!encoded || PyList_Append(data.get(), encoded.get()) < 0) {
                    return nullptr;
                }
            }
        }
        Reference node(PyTuple_Pack(2, kind, data.get()));
        if (!node) return nullptr;
        // PyList_SetItem steals its new reference, including on failure.
        if (PyList_SetItem(nodes_.get(), index, node.release()) < 0) return nullptr;
        return ref.release();
    }
};

PyObject* encode_graph(PyObject*, PyObject* arguments) {
    PyObject* value = nullptr;
    PyObject* decimal_type = nullptr;
    PyObject* shield_type = nullptr;
    PyObject* asdict = nullptr;
    if (!PyArg_ParseTuple(arguments, "OOOO:encode_graph", &value,
                          &decimal_type, &shield_type, &asdict)) {
        return nullptr;
    }
    try {
        Encoder encoder(decimal_type, shield_type, asdict);
        if (!encoder.ready()) return nullptr;
        return encoder.graph(value);
    } catch (const std::bad_alloc&) {
        return PyErr_NoMemory();
    } catch (...) {
        PyErr_SetString(PyExc_RuntimeError, "Native checkpoint graph construction failed");
        return nullptr;
    }
}

PyObject* abi_version(PyObject*, PyObject*) {
    return PyLong_FromLong(1);
}

PyObject* source_sha256(PyObject*, PyObject*) {
    return PyUnicode_FromString(BB_CHECKPOINT_SOURCE_SHA256);
}

PyMethodDef methods[] = {
    {"encode_graph", encode_graph, METH_VARARGS,
     "Build the native VERSION 1 checkpoint graph; JSON encoding stays in Python."},
    {"abi_version", abi_version, METH_NOARGS, "Native checkpoint ABI version."},
    {"source_sha256", source_sha256, METH_NOARGS, "SHA256 of this compiled C++ source."},
    {nullptr, nullptr, 0, nullptr}
};

PyModuleDef module = {
    PyModuleDef_HEAD_INIT,
    "_bb_checkpoint",
    "Exact VERSION 1 checkpoint graph construction using the CPython stable ABI.",
    0,
    methods,
    nullptr,
    nullptr,
    nullptr,
    nullptr
};

}  // namespace

PyMODINIT_FUNC PyInit__bb_checkpoint() {
    return PyModule_Create(&module);
}
