function toast(message, type='success'){
  const zone=document.getElementById('toast-zone'); if(!zone) return;
  const el=document.createElement('div'); el.className=`toast ${type}`; el.textContent=message; zone.appendChild(el);
  setTimeout(()=>{el.style.opacity='0';el.style.transform='translateY(8px)';},2800);
  setTimeout(()=>el.remove(),3400);
}

const csrfToken=document.querySelector('meta[name="csrf-token"]')?.content || '';
document.addEventListener('DOMContentLoaded',()=>{
  const permissionBoxes=[...document.querySelectorAll('.approval-permissions input[name="permissions"]')];
  const permissionSummary=document.querySelector('[data-permission-summary]');
  const updatePermissionSummary=()=>{
    if(!permissionSummary) return;
    const count=permissionBoxes.filter(box=>box.checked).length;
    permissionSummary.textContent=count ? `${count} permission${count===1?'':'s'} selected` : 'Select permissions to continue';
  };
  permissionBoxes.forEach(box=>box.addEventListener('change',updatePermissionSummary));
  document.querySelector('[data-select-permissions]')?.addEventListener('click',()=>{
    permissionBoxes.forEach(box=>{box.checked=['Login Code','Verification Code','Verify Email'].includes(box.value);});
    updatePermissionSummary();
  });
  const verificationModal=document.getElementById('verification-permission-modal');
  const verificationForm=document.querySelector('.approval-form');
  const closeVerificationModal=()=>{
    if(!verificationModal) return;
    verificationModal.classList.remove('open');
    verificationModal.setAttribute('aria-hidden','true');
    document.body.classList.remove('modal-open');
    verificationForm?.querySelector('button[type="submit"],button:not([type])')?.focus();
  };
  const openVerificationModal=()=>{
    if(!verificationModal) return false;
    verificationModal.classList.add('open');
    verificationModal.setAttribute('aria-hidden','false');
    document.body.classList.add('modal-open');
    verificationModal.querySelector('[data-close-verification-modal]')?.focus();
    return true;
  };
  verificationModal?.querySelector('[data-close-verification-modal]')?.addEventListener('click',closeVerificationModal);
  verificationModal?.addEventListener('click',(event)=>{if(event.target===verificationModal) closeVerificationModal();});
  verificationModal?.querySelector('[data-proceed-verification]')?.addEventListener('click',()=>{
    if(!verificationForm) return;
    verificationForm.dataset.confirmed='true';
    closeVerificationModal();
    verificationForm.requestSubmit();
  });
  verificationModal?.addEventListener('keydown',(event)=>{
    if(event.key==='Escape'){event.preventDefault();closeVerificationModal();return;}
    if(event.key!=='Tab') return;
    const focusable=[...verificationModal.querySelectorAll('button:not([disabled])')];
    if(!focusable.length) return;
    const first=focusable[0]; const last=focusable[focusable.length-1];
    if(event.shiftKey && document.activeElement===first){event.preventDefault();last.focus();}
    else if(!event.shiftKey && document.activeElement===last){event.preventDefault();first.focus();}
  });
  document.querySelectorAll('form[method="post"], form[method="POST"]').forEach(form=>{
    if(!form.querySelector('input[name="_csrf_token"]')){
      const input=document.createElement('input'); input.type='hidden'; input.name='_csrf_token'; input.value=csrfToken; form.appendChild(input);
    }
    form.addEventListener('submit',(event)=>{
      if(form===verificationForm && !form.dataset.confirmed && permissionBoxes.some(box=>box.checked && box.value==='Verification Code')){
        event.preventDefault();
        openVerificationModal();
        return;
      }
      const submit=form.querySelector('button[type="submit"],button:not([type])');
      if(submit){submit.dataset.originalText=submit.textContent;submit.textContent='Working…';submit.disabled=true;}
    });
  });
  const selectAll=document.getElementById('select-all-emails');
  const selects=[...document.querySelectorAll('.email-select')];
  const countLabel=document.querySelector('.bulk-toolbar .muted');
  const updateSelection=()=>{
    const count=selects.filter(item=>item.checked).length;
    if(countLabel) countLabel.textContent=count ? `${count} email${count===1?'':'s'} selected.` : 'Select emails from the table below.';
    if(selectAll) selectAll.checked=selects.length>0 && count===selects.length;
  };
  selectAll?.addEventListener('change',()=>{selects.forEach(item=>item.checked=selectAll.checked);updateSelection();});
  selects.forEach(item=>item.addEventListener('change',updateSelection));
});

function prependActivity(payload){
  const feed=document.getElementById('live-feed'); if(!feed) return;
  const el=document.createElement('div'); el.className='activity-item';
  const time=(payload.created_at||'').slice(11,19);
  el.innerHTML=`<span>${time}</span>${payload.message}`;
  feed.prepend(el);
  while(feed.children.length>20){feed.lastElementChild.remove();}
}

async function refreshStats(){
  if(!window.enableDashboardRefresh) return;
  try{
    const res=await fetch('/api/dashboard/stats'); if(!res.ok) return;
    const data=await res.json();
    document.querySelectorAll('[data-stat]').forEach(el=>{const k=el.dataset.stat;if(k in data) el.textContent=data[k];});
  }catch(e){}
}

const searchForm=document.getElementById('search-form');
const lockModal=document.getElementById('lock-modal');
const lockModalText=document.getElementById('lock-modal-text');
const lockModalPassword=document.getElementById('lock-modal-password');
const lockModalSubmit=document.getElementById('lock-modal-submit');
let pendingSearch=null;

function openLockModal(label, onUnlock){
  if(!lockModal){ onUnlock(''); return; }
  if(lockModalText) lockModalText.textContent=`"${label}" is locked. Enter the password to continue.`;
  if(lockModalPassword) lockModalPassword.value='';
  pendingSearch=onUnlock;
  lockModal.classList.add('open');
  lockModal.setAttribute('aria-hidden','false');
  setTimeout(()=>lockModalPassword?.focus(),30);
}
function closeLockModal(){
  if(!lockModal) return;
  lockModal.classList.remove('open');
  lockModal.setAttribute('aria-hidden','true');
  pendingSearch=null;
}
if(lockModalSubmit){
  lockModalSubmit.addEventListener('click', ()=>{
    const pw=(lockModalPassword?.value || '').trim();
    if(!pw){ toast('Enter the password','error'); return; }
    const cb=pendingSearch;
    closeLockModal();
    if(cb) cb(pw);
  });
}
document.querySelector('[data-close-lock]')?.addEventListener('click', closeLockModal);
lockModal?.addEventListener('click', (e)=>{ if(e.target===lockModal) closeLockModal(); });
lockModalPassword?.addEventListener('keydown', (e)=>{ if(e.key==='Enter') lockModalSubmit?.click(); });

async function doSearch(form, locked, lockPassword){
  const submit=form.querySelector('button[type="submit"],button:not([type])');
  const originalSubmitText=submit?.dataset.originalText || submit?.textContent || 'Execute Search';
  const scanner=document.getElementById('scanner');
  const results=document.getElementById('results');
  scanner?.classList.remove('hidden');
  results.innerHTML='';
  const fd=new FormData(form);
  const payload={category:fd.get('category'), emails:fd.get('emails')};
  if(locked) payload.password=lockPassword;
  const controller=new AbortController();
  const timeoutId=setTimeout(()=>controller.abort(),45000);
  try{
    const res=await fetch('/api/search',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrfToken},body:JSON.stringify(payload),signal:controller.signal});
    const contentType=res.headers.get('content-type') || '';
    const data=contentType.includes('application/json')
      ? await res.json()
      : {ok:false,error:res.status===401 ? 'Please log in again.' : `Server returned ${res.status}.`};
    if(!res.ok || !data.ok){toast(data.error || 'Search failed','error'); return;}
    if(data.denied && data.denied.length){toast(`${data.denied.length} email(s) denied/not assigned`,'error');}
    for(const item of data.results){
      const card=document.createElement('article');
      card.className=`result-card ${item.status}`;
      const firstItem=(item.items && item.items[0]) ? item.items[0] : '';
      card.innerHTML=`
        <div class="panel-head"><h2>${item.status==='found'?'✅':item.status==='not_found'?'⚠️':'❌'} ${item.email}</h2><span class="badge ${item.status}">${item.status}</span></div>
        <pre>${escapeHtml(item.result)}</pre>
        <div class="actions">
          <button class="btn btn-small" data-copy="${escapeAttr(firstItem || item.result)}">Copy</button>
          ${firstItem && firstItem.startsWith('http') ? `<a class="btn btn-small btn-primary" href="${escapeAttr(firstItem)}" target="_blank" rel="noopener">Open Link</a>`:''}
          <span class="muted">${item.fetch_time}s</span>
        </div>`;
      results.appendChild(card);
    }
    toast('Search completed','success');
  }catch(err){toast(err.name==='AbortError' ? 'IMAP search timed out. Check the mailbox settings.' : 'Search error: '+err.message,'error')}
  finally{
    clearTimeout(timeoutId);
    scanner?.classList.add('hidden');
    if(submit){
      submit.textContent=originalSubmitText;
      submit.disabled=false;
      delete submit.dataset.originalText;
    }
    refreshStats();
  }
}

if(searchForm){
  searchForm.addEventListener('submit', (e)=>{
    e.preventDefault();
    const selected=searchForm.querySelector('input[name="category"]:checked');
    const locked=!!(selected && selected.dataset.locked==='1');
    const label=selected?.closest('.category-card')?.querySelector('strong')?.textContent || 'Category';
    if(locked){
      openLockModal(label, (pw)=>doSearch(searchForm, true, pw));
      return;
    }
    doSearch(searchForm, false, '');
  });
}

document.addEventListener('click', async (e)=>{
  const btn=e.target.closest('[data-copy]');
  if(btn){ await navigator.clipboard.writeText(btn.dataset.copy || ''); toast('Copied'); }
});

function escapeHtml(str){return String(str||'').replace(/[&<>"]/g, s=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[s]));}
function escapeAttr(str){return escapeHtml(str).replace(/'/g,'&#39;')}

document.querySelectorAll('.perm-toggle').forEach(t=>{
  t.addEventListener('change', async ()=>{
    const enabling=t.checked;
    let confirmDanger=false;
    if(t.dataset.key === 'Verification Code' && enabling){
      const ok=confirm(
        'Are you really sure you want to give Verification Code permission to this user?\n\n' +
        'Warning: this code may allow the user to change/verify account email or sensitive account settings. Only enable it for trusted users.'
      );
      if(!ok){ t.checked=false; return; }
      confirmDanger=true;
    }
    const body=new URLSearchParams();
    body.append('permission_key',t.dataset.key);
    body.append('enabled',enabling?'1':'0');
    if(confirmDanger) body.append('confirm_danger','1');
    const res=await fetch('/users/'+encodeURIComponent(t.dataset.user)+'/permission',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded','X-CSRF-Token':csrfToken},body});
    if(res.ok){
      toast('Permission updated');
    }else{
      let data={};
      try{data=await res.json()}catch(e){}
      toast(data.error || 'Permission update failed','error');
      t.checked=!t.checked;
    }
  });
});

setInterval(refreshStats, 10000);

document.addEventListener('change', (e)=>{
  if(e.target && e.target.id === 'select-all-emails'){
    document.querySelectorAll('.email-select').forEach(cb=>{cb.checked=e.target.checked;});
  }
});

// API guide: copy buttons and language tabs
async function copyText(text, button){
  try{
    await navigator.clipboard.writeText(text);
    const original=button?.innerHTML;
    if(button){
      button.innerHTML='Copied ✓';
      setTimeout(()=>{button.innerHTML=original;},1600);
    }
    if(typeof toast === 'function') toast('Copied to clipboard');
  }catch(e){
    if(typeof toast === 'function') toast('Copy failed — please copy it manually','error');
  }
}

document.querySelectorAll('[data-copy-text]').forEach(button=>{
  button.addEventListener('click',()=>copyText(button.dataset.copyText || '',button));
});
document.querySelectorAll('[data-copy-target]').forEach(button=>{
  button.addEventListener('click',()=>{
    const target=document.getElementById(button.dataset.copyTarget);
    copyText(target?.innerText || '',button);
  });
});
document.querySelectorAll('[data-code-tab]').forEach(tab=>{
  tab.addEventListener('click',()=>{
    const name=tab.dataset.codeTab;
    document.querySelectorAll('[data-code-tab]').forEach(item=>item.classList.toggle('active',item===tab));
    document.querySelectorAll('[data-code-pane]').forEach(pane=>pane.classList.toggle('active',pane.dataset.codePane===name));
    const copyButton=document.querySelector('[data-copy-target]');
    const activePane=document.querySelector(`[data-code-pane="${name}"]`);
    if(copyButton && activePane) copyButton.dataset.copyTarget=activePane.id || '';
  });
});

// Responsive mobile menu
const menuBtn=document.querySelector('.mobile-menu-btn');
const sidebar=document.querySelector('.sidebar');
const sidebarBackdrop=document.querySelector('.sidebar-backdrop');
function setMenu(open){
  if(!sidebar) return;
  sidebar.classList.toggle('open',open);
  sidebarBackdrop?.classList.toggle('open',open);
  document.body.classList.toggle('menu-open',open);
  menuBtn?.setAttribute('aria-expanded',open?'true':'false');
  if(menuBtn) menuBtn.textContent=open?'×':'☰';
}
menuBtn?.addEventListener('click',()=>setMenu(!sidebar?.classList.contains('open')));
sidebarBackdrop?.addEventListener('click',()=>setMenu(false));
document.querySelectorAll('.sidebar .nav-link,.sidebar .logout').forEach(a=>a.addEventListener('click',()=>setMenu(false)));

// User expiry calendar: click any date and inspect emails for that date
const calendarModal=document.getElementById('calendar-modal');
const calendarTitle=document.getElementById('calendar-modal-title');
const calendarBody=document.getElementById('calendar-modal-body');
function openCalendarModal(date,mails){
  if(!calendarModal || !calendarTitle || !calendarBody) return;
  calendarTitle.textContent=date;
  if(!Array.isArray(mails) || mails.length===0){
    calendarBody.innerHTML='<div class="empty-state">No email is expiring on this date.</div>';
  }else{
    calendarBody.innerHTML=mails.map(mail=>`
      <div class="modal-mail">
        <code>${escapeHtml(mail.email)}</code>
        <span class="badge ${mail.status==='Expired'?'expired':'active'}">${escapeHtml(mail.status)}</span>
      </div>`).join('');
  }
  calendarModal.classList.add('open');
  calendarModal.setAttribute('aria-hidden','false');
}
function closeCalendarModal(){
  calendarModal?.classList.remove('open');
  calendarModal?.setAttribute('aria-hidden','true');
}
document.querySelectorAll('.calendar-day-btn').forEach(btn=>{
  btn.addEventListener('click',()=>{
    let mails=[];
    try{mails=JSON.parse(btn.dataset.mails||'[]')}catch(e){mails=[]}
    openCalendarModal(btn.dataset.date || 'Selected date',mails);
  });
});
document.querySelector('[data-close-calendar]')?.addEventListener('click',closeCalendarModal);
calendarModal?.addEventListener('click',(e)=>{if(e.target===calendarModal) closeCalendarModal();});
document.addEventListener('keydown',(e)=>{if(e.key==='Escape') {closeCalendarModal(); setMenu(false);}});

// Tap/click safety: never let the mobile backdrop trap the page.
document.addEventListener('DOMContentLoaded', () => {
  const bd = document.querySelector('.sidebar-backdrop');
  if (bd) {
    bd.style.pointerEvents = 'none';
  }
  // Clear stale menu state after browser bfcache/refresh quirks.
  if (document.body.classList.contains('menu-open') && !document.querySelector('.sidebar.open')) {
    document.body.classList.remove('menu-open');
  }
});
window.addEventListener('pageshow', () => {
  const bd = document.querySelector('.sidebar-backdrop');
  if (bd) bd.style.pointerEvents = 'none';
});
