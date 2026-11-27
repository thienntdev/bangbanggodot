// Local-only management UI. All validation, ownership, prices, grants and
// idempotency are authoritative on the server; a send creates mail, not items.
const $=id=>document.getElementById(id);
const count=value=>Number(value).toLocaleString('vi-VN');
const node=(tag,text,className)=>{const result=document.createElement(tag);if(text!=null)result.textContent=text;if(className)result.className=className;return result;};
const STORE='bangbang.m29.pending-mail.v1';
const state={csrf:'',authenticated:false,recipient:null,cart:new Map(),preview:null,intent:null,
  sending:false,previewing:false,recipientOffset:0,catalogOffset:0,recipientTotal:0,catalogTotal:0,
  recipientEpoch:0,catalogEpoch:0,catalogCategory:'all',generation:0,storageFault:false,pendingNotice:''};
const utf8=value=>new TextEncoder().encode(value).length;
const keyFor=row=>`${row.kind}:${row.id}`;
const id=()=>globalThis.crypto?.randomUUID?.()||`${Date.now().toString(16)}-${Array.from(globalThis.crypto.getRandomValues(new Uint32Array(4)),n=>n.toString(16)).join('-')}`;
const locked=()=>state.sending||state.previewing||!!state.intent||state.storageFault;
const message=(text,error=false,target='global-message')=>{const box=$(target);box.textContent=text||'';box.classList.toggle('is-error',error);};
class ApiError extends Error{constructor(message,status=0,code='network',reply=null){super(message);this.status=status;this.code=code;this.notCreated=reply?.not_created===true;this.requestId=reply?.request_id;}}

async function api(path,{method='GET',body,timeout=15000}={}){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
  try{
    const headers={Accept:'application/json'};
    if(method!=='GET'){headers['Content-Type']='application/json';if(state.csrf)headers['X-CSRF-Token']=state.csrf;}
    const response=await fetch(`/api/admin/${path}`,{method,body:body===undefined?undefined:JSON.stringify(body),
      headers,credentials:'same-origin',cache:'no-store',redirect:'error',signal:controller.signal});
    let data;try{data=await response.json();}catch{throw new ApiError('Server không trả về dữ liệu quản trị hợp lệ.',response.status,'invalid_response');}
    if(!response.ok||data.ok!==true){
      const error=new ApiError(data.error?.message||`Yêu cầu bị từ chối (${response.status}).`,response.status,data.error?.code||'rejected',data.error);
      if(response.status===401){state.csrf='';setAuthenticated(false);message('Phiên quản trị hết hạn. Mở khóa lại; yêu cầu gửi đang chờ vẫn giữ nguyên mã.',true,'unlock-message');}
      throw error;
    }
    return data;
  }catch(error){if(error instanceof ApiError)throw error;throw new ApiError(error.name==='AbortError'?'Hết thời gian chờ server.':'Không kết nối được tới server.');}
  finally{clearTimeout(timer);}
}

function setAuthenticated(value){
  state.authenticated=value;state.generation++;$('workspace').hidden=!value;$('unlock-panel').hidden=value;$('logout').hidden=!value;
  $('session-status').textContent=value?'Cục bộ · Đã mở khóa':'Cục bộ · Đã khóa';$('session-status').classList.toggle('is-ready',value);
  globalThis.bbAdminAccounts?.setAuthenticated(value);
  if(value)void refreshLogging();else{$('logging-toggle').disabled=true;loggingEnabled=null;}
}
let loggingEnabled=null,loggingBusy=false;
async function refreshLogging(){
  const generation=state.generation;$('logging-toggle').disabled=true;
  try{const result=await api('logging');if(generation!==state.generation||!state.authenticated)return;
    loggingEnabled=result.enabled;$('logging-status').textContent=result.enabled?'Đang ghi log chẩn đoán.':'Đã tắt ghi log.';
    $('logging-toggle').textContent=result.enabled?'Tắt ghi log':'Bật ghi log';
    $('logging-toggle').setAttribute('aria-pressed',String(result.enabled));
  }catch(error){if(generation===state.generation)$('logging-status').textContent=error.message;}
  finally{if(generation===state.generation)$('logging-toggle').disabled=!state.authenticated||loggingBusy||loggingEnabled===null;}
}
$('logging-toggle').addEventListener('click',async()=>{
  if(loggingBusy||!state.authenticated||loggingEnabled===null)return;
  loggingBusy=true;$('logging-toggle').disabled=true;
  try{await api('logging',{method:'POST',body:{enabled:!loggingEnabled}});}
  catch(error){$('logging-status').textContent=error.message;}
  finally{loggingBusy=false;if(state.authenticated)await refreshLogging();}
});
function invalidatePreview(){state.preview=null;$('preview-panel').hidden=true;}
function syncControls(){
  for(const el of document.querySelectorAll('#compose-form input,#compose-form textarea,#cart input,#cart button,.person,.catalog-item button'))el.disabled=locked();
  $('preview-button').disabled=locked()||!state.recipient||!state.cart.size;
  $('preview-button').textContent=state.previewing?'Đang kiểm tra…':'Kiểm tra trước khi gửi →';
  $('confirm-send').disabled=state.storageFault||state.sending||!state.preview?.can_send||!!state.intent&&!state.preview?.retry;
  $('retry-send').disabled=state.storageFault||state.sending;
  $('retry-send').textContent=state.sending?'Đang xác nhận…':'Kiểm tra / gửi lại cùng mã';
  $('renew-preview').disabled=state.storageFault||state.sending||state.previewing;
  $('cancel-preview').disabled=state.sending||!!state.intent;
  $('logout').disabled=state.sending;
  $('recipient-prev').disabled=state.recipientOffset<=0;
  $('recipient-next').disabled=state.recipientOffset+25>=state.recipientTotal;
  $('catalog-prev').disabled=state.catalogOffset<=0;
  $('catalog-next').disabled=state.catalogOffset+40>=state.catalogTotal;
  globalThis.bbAdminAccounts?.sync();
}
function persistIntent(){
  try{const value=JSON.stringify(state.intent);sessionStorage.setItem(STORE,value);
    if(sessionStorage.getItem(STORE)!==value)throw new Error('Storage round-trip failed');
  }catch{throw new ApiError('Chưa gửi yêu cầu: không lưu được mã chống gửi trùng trên tab này. Cho phép bộ nhớ trang rồi thử lại cùng mã; không đóng tab đang chờ.',0,'storage');}
}
function clearIntent(){
  // Never unlock a new draft while an old intent can reappear after reload.
  try{sessionStorage.removeItem(STORE);if(sessionStorage.getItem(STORE)!==null)throw new Error('Storage removal failed');}
  catch{throw new ApiError('Chưa xóa được trạng thái gửi trên tab. Giữ nguyên mã và thử lại khi bộ nhớ trang hoạt động.',0,'storage');}
  state.intent=null;state.pendingNotice='';
}
function validIntent(value){
  const object=x=>x!==null&&typeof x==='object'&&!Array.isArray(x);
  const keys=(x,expected)=>object(x)&&Object.keys(x).sort().join(',')===[...expected].sort().join(',');
  const text=(x,max,bytes,required=false)=>typeof x==='string'&&(!required||x.length>0)&&[...x].length<=max&&utf8(x)<=bytes;
  const integer=(x,max)=>Number.isSafeInteger(x)&&x>=1&&x<=max;
  if(!keys(value,['recipient','subject','body','rewards','request_id','preview_token'])
    ||typeof value.request_id!=='string'||!/^[A-Za-z0-9_-]{1,64}$/.test(value.request_id)
    ||!text(value.preview_token,512,512,true)||!keys(value.recipient,['id','name'])
    ||!integer(value.recipient.id,0xffffffff)||!text(value.recipient.name,128,512,true)
    ||!text(value.subject,80,240,true)||!text(value.body,2000,6000)
    ||!Array.isArray(value.rewards)||value.rewards.length<1||value.rewards.length>16)return false;
  const seen=new Set();
  return value.rewards.every(row=>{
    if(!keys(row,['kind','id','quantity'])||!integer(row.quantity,0x7fffffff))return false;
    if(row.kind==='currency'?!['cash','golden','gift'].includes(row.id):!['tank','item'].includes(row.kind)||!integer(row.id,0xffffffff))return false;
    const key=keyFor(row);if(seen.has(key))return false;seen.add(key);return true;
  });
}
function restoreIntent(){
  try{const stored=sessionStorage.getItem(STORE);
    if(stored!==null){const value=JSON.parse(stored);if(!validIntent(value))throw new Error('Invalid pending intent');state.intent=value;}
  }catch{state.storageFault=true;message('Không đọc được trạng thái gửi trước đó. Chưa cho gửi thư mới để tránh trùng quà. Cho phép bộ nhớ trang rồi tải lại; không tự xóa dữ liệu của tab đang chờ.',true);}
  renderPending();
}
function renderPending(){
  $('pending-banner').hidden=!state.intent;
  if(state.intent){$('pending-message').textContent=state.pendingNotice||`Thư cho ${state.intent.recipient.name} (ID ${state.intent.recipient.id}). Chưa xác nhận được đã tạo thư hay chưa. Dùng lại đúng mã này để tránh gửi trùng; không tạo thư khác thay thế.`;$('pending-key').textContent=state.intent.request_id;}
  syncControls();
}
function selectRecipient(row){
  if(locked())return;state.recipient={id:row.id,name:row.name};invalidatePreview();
  const box=$('recipient-selected');box.replaceChildren(node('p','ĐÃ CHỌN','eyebrow'),node('strong',row.name),node('span',`ID ${row.id} · ${row.username}`));
  for(const button of $('recipient-results').querySelectorAll('button'))button.setAttribute('aria-pressed',String(button.dataset.id===String(row.id)));
  syncControls();
}
async function loadRecipients(reset=false){
  if(!state.authenticated)return;if(reset)state.recipientOffset=0;
  const epoch=++state.recipientEpoch,generation=state.generation,offset=state.recipientOffset;
  $('recipient-results').replaceChildren(node('p','Đang tìm nhân vật…','empty'));
  try{const data=await api(`recipients?${new URLSearchParams({q:$('recipient-query').value.trim(),offset,limit:25})}`);
    if(epoch!==state.recipientEpoch||generation!==state.generation||!state.authenticated)return;
    state.recipientTotal=data.total;const box=$('recipient-results');box.replaceChildren();
    for(const row of data.rows){const button=node('button',null,'person');button.type='button';button.dataset.id=row.id;
      button.setAttribute('aria-pressed',String(row.id===state.recipient?.id));button.append(node('strong',row.name),node('span',`ID ${row.id} · ${row.username}`));
      button.addEventListener('click',()=>selectRecipient(row));box.append(button);}
    if(!data.rows.length)box.append(node('p','Không có nhân vật phù hợp. Tạo nhân vật trong game trước nếu tài khoản chưa có nhân vật.','empty'));
    $('recipient-count').textContent=data.total?`${offset+1}–${offset+data.rows.length} / ${count(data.total)}`:'0 nhân vật';syncControls();
  }catch(error){if(epoch===state.recipientEpoch&&generation===state.generation)$('recipient-results').replaceChildren(node('p',error.message,'empty'));}
}
const symbols={currency:'XU',tank:'TK',crystal:'TT',material:'NL',helper:'TT',avatar:'AV',background:'BG',halo:'VS',skin:'SK'};
async function loadCatalog(reset=false){
  if(!state.authenticated)return;if(reset)state.catalogOffset=0;
  const epoch=++state.catalogEpoch,generation=state.generation,offset=state.catalogOffset;
  $('catalog-results').replaceChildren(node('p','Đang đọc danh mục hỗ trợ…','empty'));
  try{const data=await api(`catalog?${new URLSearchParams({q:$('catalog-query').value.trim(),category:$('catalog-category').value,offset,limit:40})}`);
    if(epoch!==state.catalogEpoch||generation!==state.generation||!state.authenticated)return;
    state.catalogTotal=data.total;const category=$('catalog-category'),selected=category.value;
    category.replaceChildren(new Option('Tất cả','all'));
    for(const row of data.categories||[])if(row.id!=='all')category.add(new Option(row.label,row.id));
    category.value=[...category.options].some(x=>x.value===selected)?selected:'all';
    const box=$('catalog-results');box.replaceChildren();
    for(const row of data.rows){const card=node('article',null,'catalog-item'),info=node('div',null,'item-info');
      info.append(node('strong',row.name),node('p',`${row.kind==='currency'?'Tiền':`Mã ${row.id}`}${row.unique?' · Vĩnh viễn / không trùng':''}${row.level?` · Cấp ${row.level}`:''}`));
      if(row.note){info.append(node('p',row.note));}
      const add=node('button','+ Thêm');add.type='button';add.setAttribute('aria-label',`Thêm ${row.name}`);add.addEventListener('click',()=>addReward(row));
      card.append(node('span',symbols[row.category]||'ĐỒ','item-symbol'),info,add);box.append(card);}
    if(!data.rows.length)box.append(node('p','Không có vật phẩm được hỗ trợ khớp với tìm kiếm.','empty'));
    $('catalog-count').textContent=data.total?`${offset+1}–${offset+data.rows.length} / ${count(data.total)}`:'0 vật phẩm';syncControls();
  }catch(error){if(epoch===state.catalogEpoch&&generation===state.generation)$('catalog-results').replaceChildren(node('p',error.message,'empty'));}
}
function addReward(row){
  if(locked())return;const key=keyFor(row),before=state.cart.get(key);
  if(!before&&state.cart.size>=16){message('Một thư tối đa 16 loại đính kèm.',true);return;}
  const max=Number(row.max_quantity)||1;
  if(before&&before.quantity>=max){message(`${row.name} đã đạt giới hạn ${count(max)} trong một thư.`,true);return;}
  state.cart.set(key,{...row,quantity:before?before.quantity+1:1});invalidatePreview();renderCart();message('');
}
function renderCart(){
  const box=$('cart');box.replaceChildren();$('cart-count').textContent=`${state.cart.size} / 16 phần đính kèm`;
  for(const [key,row] of state.cart){const line=node('div',null,'cart-row'),name=node('strong',row.name);
    name.append(node('small',row.kind==='currency'?'Tiền':`Mã ${row.id}`));
    const input=node('input');input.type='number';input.min='1';input.max=String(row.max_quantity||1);input.step='1';input.value=row.quantity;input.inputMode='numeric';input.setAttribute('aria-label',`Số lượng ${row.name}`);
    input.addEventListener('input',()=>{if(locked())return;invalidatePreview();const value=Number(input.value);
      if(Number.isSafeInteger(value)&&value>=1&&value<=Number(input.max)){row.quantity=value;input.setCustomValidity('');}
      else input.setCustomValidity(`Số nguyên từ 1 đến ${count(input.max)}.`);});
    const remove=node('button','×');remove.type='button';remove.setAttribute('aria-label',`Bỏ ${row.name}`);remove.addEventListener('click',()=>{if(locked())return;state.cart.delete(key);invalidatePreview();renderCart();});
    line.append(name,input,remove);box.append(line);}
  if(!state.cart.size)box.append(node('p','Chọn vật phẩm ở kho để thêm vào thư.','empty'));syncControls();
}
function payload(){
  for(const input of $('cart').querySelectorAll('input'))if(!input.reportValidity())throw new Error('Kiểm tra lại số lượng phần quà.');
  const subject=$('subject').value.trim(),body=$('body').value.trim();
  if(!subject||subject.length>80||utf8(subject)>240)throw new Error('Tiêu đề cần 1–80 ký tự, tối đa 240 byte UTF-8.');
  if(body.length>2000||utf8(body)>6000)throw new Error('Lời nhắn tối đa 2000 ký tự / 6000 byte UTF-8.');
  if(!state.recipient||!state.cart.size)throw new Error('Chọn đúng người nhận và ít nhất một phần quà.');
  return {recipient:{...state.recipient},subject,body,rewards:[...state.cart.values()].map(({kind,id,quantity})=>({kind,id,quantity}))};
}
async function preview(){
  if(locked()||!state.authenticated)return;let draft;try{draft=payload();}catch(error){message(error.message,true);return;}
  state.previewing=true;invalidatePreview();$('receipt').hidden=true;syncControls();message('');const generation=state.generation;
  try{const result=await api('mail/preview',{method:'POST',body:draft});
    if(generation!==state.generation||!state.authenticated)return;
    const canonical={recipient:{id:result.recipient.id,name:result.recipient.name},subject:result.subject,body:result.body,rewards:result.rewards.map(({kind,id,quantity})=>({kind,id,quantity}))};
    state.preview={...result,payload:canonical};
    $('preview-recipient').textContent=`Gửi tới ${result.recipient.name} · ID ${result.recipient.id}`;
    $('preview-subject').textContent=result.subject;$('preview-body').textContent=result.body;
    $('preview-rewards').replaceChildren(...result.rewards.map(row=>node('li',`${row.name} × ${count(row.quantity)}`)));
    $('preview-warnings').replaceChildren(...(result.warnings||[]).map(w=>node('li',typeof w==='string'?w:w.message||w.code||'Cần kiểm tra phần quà.')));
    $('preview-panel').hidden=false;$('preview-panel').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'nearest'});
    if(!result.can_send)message('Chưa thể gửi. Xem các điều kiện cần sửa trong phần xác nhận.',true);
  }catch(error){message(error.message,true);}finally{state.previewing=false;syncControls();}
}
async function sendMail(retry=false){
  if(state.storageFault||state.sending||!state.authenticated)return;
  if(!retry&&state.intent&&state.preview?.retry&&state.preview.can_send){state.intent={...state.intent,preview_token:state.preview.preview_token};retry=true;}
  if(!retry){if(!state.preview?.can_send||state.intent)return;state.intent={...state.preview.payload,preview_token:state.preview.preview_token,request_id:id()};}
  if(!state.intent)return;
  try{persistIntent();}catch(error){state.pendingNotice=error.message;renderPending();message(error.message,true);return;}
  state.pendingNotice='';state.sending=true;renderPending();syncControls();message('Đang xác nhận tạo thư trên server…');
  try{const result=await api('mail/send',{method:'POST',body:state.intent,timeout:20000});
    if(result.request_id!==state.intent.request_id||!result.mail_id)throw new ApiError('Phản hồi không khớp mã gửi; cần kiểm tra lại bằng cùng mã.',0,'correlation');
    const box=$('receipt');box.replaceChildren(node('strong',result.duplicate?'Đã xác nhận thư có sẵn — không gửi trùng.':'Đã tạo thư thành công.'),
      node('p',`${result.recipient.name} (ID ${result.recipient.id}) mở Hòm thư trong game để nhận.`),node('code',result.mail_id));box.hidden=false;
    state.pendingNotice='Server đã xác nhận thư này được tạo. Đang xóa trạng thái chờ trên tab; nếu chưa xóa được, thử lại cùng mã chỉ kiểm tra biên nhận, không tạo thêm thư.';
    clearIntent();invalidatePreview();state.cart.clear();renderCart();$('renew-preview').hidden=true;message('Thư đã được lưu. Chưa cộng đồ vào túi cho tới khi người chơi nhận thư.');
  }catch(error){
    const proofExpired=['preview_expired','preview_required'].includes(error.code);
    const notCreated=[400,409].includes(error.status)&&error.notCreated&&error.requestId===state.intent?.request_id
      &&!proofExpired&&!['idempotency_conflict','admin_required','csrf_invalid','unlock_failed'].includes(error.code);
    if(notCreated){
      state.pendingNotice='Server xác nhận chưa tạo thư này. Đang xóa trạng thái chờ để cho sửa nội dung.';
      try{clearIntent();invalidatePreview();$('renew-preview').hidden=true;
        if(error.code.startsWith('recipient_')){state.recipient=null;$('recipient-selected').replaceChildren(node('span','Chọn lại nhân vật theo tên hiện tại.','muted'));
          for(const button of $('recipient-results').querySelectorAll('button'))button.setAttribute('aria-pressed','false');}
        message(`${error.message} Server xác nhận chưa tạo thư. Có thể sửa người nhận/phần quà rồi kiểm tra lại trước khi gửi.`,true);
      }catch(storageError){message(`${error.message} ${storageError.message}`,true);}
    }else{
      $('renew-preview').hidden=!proofExpired;
      message(`${error.message} Giữ nguyên mã yêu cầu đang chờ. Có thể mở khóa lại rồi kiểm tra / gửi lại cùng mã; server không tạo thư thứ hai cho mã này.`,true);
    }
  }finally{state.sending=false;renderPending();syncControls();}
}
async function renewPendingPreview(){
  if(state.storageFault||!state.intent||state.sending||state.previewing||!state.authenticated)return;
  state.previewing=true;syncControls();const generation=state.generation;
  const {recipient,subject,body,rewards}=state.intent;
  try{
    const result=await api('mail/preview',{method:'POST',body:{recipient,subject,body,rewards}});
    if(generation!==state.generation||!state.intent)return;
    state.preview={...result,retry:true};
    $('preview-recipient').textContent=`Xác nhận lại ${result.recipient.name} · ID ${result.recipient.id} · GIỮ NGUYÊN mã gửi`;
    $('preview-subject').textContent=result.subject;$('preview-body').textContent=result.body;
    $('preview-rewards').replaceChildren(...result.rewards.map(row=>node('li',`${row.name} × ${count(row.quantity)}`)));
    $('preview-warnings').replaceChildren(...(result.warnings||[]).map(w=>node('li',typeof w==='string'?w:w.message||w.code)));
    $('preview-panel').hidden=false;$('preview-panel').scrollIntoView({block:'nearest'});
    message(result.can_send?'Xác nhận xem trước đã được làm mới. Kiểm tra đúng người và quà rồi bấm Xác nhận gửi thư.':'Chưa thể gửi; các phần quà đang chờ vẫn được giữ nguyên.',!result.can_send);
  }catch(error){message(error.message,true);}finally{state.previewing=false;syncControls();}
}

$('unlock-form').addEventListener('submit',async event=>{event.preventDefault();const input=$('secret'),secret=input.value;input.value='';$('unlock-submit').disabled=true;message('Đang xác thực…',false,'unlock-message');
  try{const result=await api('session',{method:'POST',body:{secret}});if(!result.authenticated||!result.csrf)throw new Error('Server chưa xác nhận phiên quản trị.');state.csrf=result.csrf;setAuthenticated(true);message('',false,'unlock-message');renderPending();await Promise.all([loadRecipients(true),loadCatalog(true)]);}
  catch(error){message(error.message,true,'unlock-message');}finally{$('unlock-submit').disabled=false;}});
$('logout').addEventListener('click',async()=>{if(state.sending)return;try{await api('logout',{method:'POST',body:{}});state.csrf='';invalidatePreview();setAuthenticated(false);message('Trang đã khóa. Yêu cầu gửi chưa rõ kết quả (nếu có) vẫn được giữ trên tab này.',false,'unlock-message');}catch(error){message(error.message,true);}});
$('recipient-search').addEventListener('submit',event=>{event.preventDefault();loadRecipients(true);});
$('catalog-search').addEventListener('submit',event=>{event.preventDefault();loadCatalog(true);});
$('catalog-category').addEventListener('change',()=>loadCatalog(true));
for(const [prefix,load,size] of [['recipient',loadRecipients,25],['catalog',loadCatalog,40]]){
  $(prefix+'-prev').addEventListener('click',()=>{state[prefix+'Offset']=Math.max(0,state[prefix+'Offset']-size);load();});
  $(prefix+'-next').addEventListener('click',()=>{state[prefix+'Offset']+=size;load();});
}
$('compose-form').addEventListener('submit',event=>{event.preventDefault();preview();});
for(const input of [$('subject'),$('body')])input.addEventListener('input',invalidatePreview);
$('cancel-preview').addEventListener('click',()=>{if(!state.sending&&!state.intent)invalidatePreview();});
$('confirm-send').addEventListener('click',()=>sendMail());$('retry-send').addEventListener('click',()=>sendMail(true));
$('renew-preview').addEventListener('click',renewPendingPreview);
globalThis.bbAdminAccounts?.connect({api,canChange:()=>!locked(),onChanged:result=>{
  if(result?.operation==='delete'&&state.recipient?.id===result.account?.profile_id){state.recipient=null;invalidatePreview();$('recipient-selected').replaceChildren(node('span','Chọn lại nhân vật đang hoạt động.','muted'));syncControls();}
  loadRecipients(true);
}});
restoreIntent();
try{const result=await api('session');
  if(!result.enabled){$('unlock-form').hidden=true;message('Web buff chưa được bật. Khởi động server bằng trình mở web buff đi kèm bản cập nhật.',false,'unlock-message');$('session-status').textContent='Chưa bật quản trị';}
  else if(result.authenticated&&result.csrf){state.csrf=result.csrf;setAuthenticated(true);await Promise.all([loadRecipients(),loadCatalog()]);}
  else setAuthenticated(false);
}catch(error){setAuthenticated(false);message(error.message,true,'unlock-message');}
