package protocol

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"io"
)

// Wire frame layout (little-endian):
//   [u16 total_length] [i16 message_id] [u32 sequence] [body...]
// Greeting: 2 bytes 0x0000

const (
	FrameHeaderSize = 8 // u16 length + i16 msgID + u32 seq
	MaxBodyBytes    = 65527
	MaxFrameSize    = 65535
	GreetingSize    = 2
)

// Writer encodes sixcube binary protocol messages.
type Writer struct {
	buf *bytes.Buffer
}

func NewWriter() *Writer {
	return &Writer{buf: bytes.NewBuffer(make([]byte, 0, 256))}
}

func (w *Writer) Reset() {
	w.buf.Reset()
}

// --- scalar writers ---

func (w *Writer) PutU8(v uint8)   { w.buf.WriteByte(v) }
func (w *Writer) PutI8(v int8)    { w.buf.WriteByte(byte(v)) }
func (w *Writer) PutU16(v uint16) { binary.Write(w.buf, binary.LittleEndian, v) }
func (w *Writer) PutI16(v int16)  { binary.Write(w.buf, binary.LittleEndian, v) }
func (w *Writer) PutU32(v uint32) { binary.Write(w.buf, binary.LittleEndian, v) }
func (w *Writer) PutI32(v int32)  { binary.Write(w.buf, binary.LittleEndian, v) }
func (w *Writer) PutF32(v float32) {
	binary.Write(w.buf, binary.LittleEndian, v)
}
func (w *Writer) PutU64Words(lo, hi uint32) {
	w.PutU32(lo)
	w.PutU32(hi)
}
func (w *Writer) PutUTF8(s string) {
	raw := []byte(s)
	w.PutU16(uint16(len(raw)))
	w.buf.Write(raw)
}

// Bytes returns the body bytes written so far.
func (w *Writer) Bytes() []byte {
	return w.buf.Bytes()
}

// BuildFrame wraps body bytes into a frame with header.
func BuildFrame(msgID int16, sequence uint32, body []byte) []byte {
	totalLen := FrameHeaderSize + len(body)
	frame := make([]byte, totalLen)
	binary.LittleEndian.PutUint16(frame[0:2], uint16(totalLen))
	binary.LittleEndian.PutUint16(frame[2:4], uint16(msgID))
	binary.LittleEndian.PutUint32(frame[4:8], sequence)
	copy(frame[8:], body)
	return frame
}

// Greeting returns the 2-byte greeting that starts every connection.
func Greeting() []byte {
	return []byte{0x00, 0x00}
}

// --- Reader decodes incoming binary frames ---

type Reader struct {
	data []byte
	pos  int
}

func NewReader(data []byte) *Reader {
	return &Reader{data: data, pos: 0}
}

func (r *Reader) Remaining() int {
	return len(r.data) - r.pos
}

func (r *Reader) need(n int) error {
	if r.Remaining() < n {
		return io.ErrUnexpectedEOF
	}
	return nil
}

func (r *Reader) GetU8() (uint8, error) {
	if err := r.need(1); err != nil {
		return 0, err
	}
	v := r.data[r.pos]
	r.pos++
	return v, nil
}

func (r *Reader) GetI8() (int8, error) {
	v, err := r.GetU8()
	return int8(v), err
}

func (r *Reader) GetU16() (uint16, error) {
	if err := r.need(2); err != nil {
		return 0, err
	}
	v := binary.LittleEndian.Uint16(r.data[r.pos:])
	r.pos += 2
	return v, nil
}

func (r *Reader) GetI16() (int16, error) {
	v, err := r.GetU16()
	return int16(v), err
}

func (r *Reader) GetU32() (uint32, error) {
	if err := r.need(4); err != nil {
		return 0, err
	}
	v := binary.LittleEndian.Uint32(r.data[r.pos:])
	r.pos += 4
	return v, nil
}

func (r *Reader) GetI32() (int32, error) {
	v, err := r.GetU32()
	return int32(v), err
}

func (r *Reader) GetF32() (float32, error) {
	if err := r.need(4); err != nil {
		return 0, err
	}
	var v float32
	buf := bytes.NewReader(r.data[r.pos : r.pos+4])
	binary.Read(buf, binary.LittleEndian, &v)
	r.pos += 4
	return v, nil
}

func (r *Reader) GetUTF8() (string, error) {
	length, err := r.GetU16()
	if err != nil {
		return "", err
	}
	if err := r.need(int(length)); err != nil {
		return "", err
	}
	s := string(r.data[r.pos : r.pos+int(length)])
	r.pos += int(length)
	return s, nil
}

func (r *Reader) GetU64Words() (lo uint32, hi uint32, err error) {
	lo, err = r.GetU32()
	if err != nil {
		return
	}
	hi, err = r.GetU32()
	return
}

// --- Frame parser (stream-level) ---

type FrameParser struct {
	buffer  []byte
	greeted bool
}

func NewFrameParser() *FrameParser {
	return &FrameParser{
		buffer:  make([]byte, 0, 4096),
		greeted: true, // server-side: client doesn't send greeting
	}
}

// NewClientFrameParser creates a parser that expects a greeting from the server.
func NewClientFrameParser() *FrameParser {
	return &FrameParser{
		buffer:  make([]byte, 0, 4096),
		greeted: false, // client-side: server sends greeting first
	}
}

// Feed appends raw data and extracts complete frames.
func (fp *FrameParser) Feed(data []byte) ([][]byte, error) {
	fp.buffer = append(fp.buffer, data...)

	if !fp.greeted {
		if len(fp.buffer) < 2 {
			return nil, nil
		}
		if fp.buffer[0] != 0 || fp.buffer[1] != 0 {
			return nil, fmt.Errorf("invalid greeting")
		}
		fp.greeted = true
		fp.buffer = fp.buffer[2:]
	}

	var frames [][]byte
	for len(fp.buffer) >= 2 {
		length := int(binary.LittleEndian.Uint16(fp.buffer[0:2]))
		if length < FrameHeaderSize {
			return nil, fmt.Errorf("frame too short: %d", length)
		}
		if len(fp.buffer) < length {
			break
		}
		frame := make([]byte, length)
		copy(frame, fp.buffer[:length])
		frames = append(frames, frame)
		fp.buffer = fp.buffer[length:]
	}

	return frames, nil
}

// ParseFrameHeader extracts message ID and sequence from a raw frame.
func ParseFrameHeader(frame []byte) (msgID int16, sequence uint32, body []byte, err error) {
	if len(frame) < FrameHeaderSize {
		return 0, 0, nil, fmt.Errorf("frame too short")
	}
	msgID = int16(binary.LittleEndian.Uint16(frame[2:4]))
	sequence = binary.LittleEndian.Uint32(frame[4:8])
	body = frame[8:]
	return
}
