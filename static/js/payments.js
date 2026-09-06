(() => {
  "use strict";
  const E={payments:"/api/payments/payments/",allocations:"/api/payments/payment-allocations/",receipts:"/api/payments/receipts/",clients:"/api/clients/clients/",suppliers:"/api/suppliers/suppliers/",employees:"/api/employees/",contractors:"/api/contractors/",clientInvoices:"/api/invoicing/client-invoices/",supplierInvoices:"/api/invoicing/supplier-invoices/",contractorInvoices:"/api/invoicing/contractor-invoices/"};
  const $=(s,r=document)=>r.querySelector(s);
  const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const money=v=>Number(v||0).toLocaleString("en-US",{style:"currency",currency:"USD",minimumFractionDigits:2});
  const state={payments:[],allocations:[],receipts:[],search:"",direction:"",ordering:"-payment_date"};
  function cookie(name){const m=document.cookie.match(new RegExp("(^|;\\s*)"+name+"=([^;]*)"));return m?decodeURIComponent(m[2]):""}
  async function api(url,options={}){
    const headers={Accept:"application/json",...(options.headers||{})};
    if(options.body)headers["Content-Type"]="application/json";
    if(options.method&&!['GET','HEAD'].includes(options.method))headers["X-CSRFToken"]=cookie("csrftoken");
    const response=await fetch(url,{credentials:"same-origin",...options,headers});
    if(!response.ok){let message=response.statusText;try{const body=await response.json();message=Object.entries(body).map(([k,v])=>`${k}: ${Array.isArray(v)?v.join(" "):v}`).join("\n")}catch(_){/* non-JSON */}throw new Error(message||`Request failed (${response.status})`)}
    return response.status===204?null:response.json();
  }
  async function all(url){const rows=[];while(url){const data=await api(url);if(Array.isArray(data))return data;rows.push(...(data.results||[]));url=data.next}return rows}
  function listUrl(){const p=new URLSearchParams({ordering:state.ordering});if(state.search)p.set("search",state.search);if(state.direction)p.set("direction",state.direction);return `${E.payments}?${p}`}
  function render(){
    const body=$("[data-payment-rows]");
    if(!state.payments.length)body.innerHTML='<tr class="empty-row"><td colspan="8"><b>No payments found</b><span>Record a payment or adjust the filters.</span></td></tr>';
    else body.innerHTML=state.payments.map(p=>`<tr><td><button class="payment-row-link" data-payment-detail="${p.id}"><strong>${esc(p.payment_number)}</strong><span>${esc(p.reference||"View details")}</span></button></td><td><span class="${p.direction==='INCOMING'?'direction-in':'direction-out'}">${p.direction==='INCOMING'?'Received':'Paid'}</span></td><td>${esc(p.payee_name||'—')}<span>${esc((p.payee_type||'').toLowerCase())}</span></td><td>${esc(p.payment_date)}</td><td>${esc(p.payment_method)}</td><td>${money(p.amount)}</td><td>${p.allocatable?money(p.unallocated_amount):'—'}</td><td><div class="payment-actions">${p.allocatable?(Number(p.unallocated_amount)>0?`<button class="quiet-button" data-allocate="${p.id}">Allocate</button>`:'<span class="status active"><i></i>Allocated</span>'):'<span class="status active"><i></i>Direct payment</span>'}${p.has_receipt?'':`<button class="quiet-button" data-receipt="${p.id}">Issue receipt</button>`}</div></td></tr>`).join('');
    const sum=(direction,field)=>state.payments.filter(p=>!direction||p.direction===direction).reduce((s,p)=>s+Number(p[field]),0);
    $("[data-metric=received]").textContent=money(sum('INCOMING','amount'));$("[data-metric=paid]").textContent=money(sum('OUTGOING','amount'));$("[data-metric=unallocated]").textContent=money(state.payments.filter(p=>p.allocatable).reduce((s,p)=>s+Number(p.unallocated_amount),0));$("[data-metric=total]").textContent=state.payments.length;
    body.querySelectorAll('[data-payment-detail]').forEach(b=>b.onclick=()=>openPaymentDetail(b.dataset.paymentDetail));body.querySelectorAll('[data-allocate]').forEach(b=>b.onclick=()=>openAllocation(b.dataset.allocate));body.querySelectorAll('[data-receipt]').forEach(b=>b.onclick=()=>issueReceipt(b.dataset.receipt));
  }
  function renderRegisters(){
    const paymentNumber=id=>state.payments.find(p=>p.id===id)?.payment_number||id.slice(0,8);
    $("[data-allocation-rows]").innerHTML=state.allocations.length?state.allocations.map(a=>`<tr><td>${esc(paymentNumber(a.payment))}</td><td>${esc((a.client_invoice||a.supplier_invoice||'—').slice(0,8))}</td><td>${money(a.allocated_amount)}</td><td><button class="payment-detail-link" data-register-allocation="${a.id}">View detail</button></td></tr>`).join(''):'<tr><td colspan="4"><strong>No allocations yet</strong></td></tr>';
    $("[data-inline-receipt-rows]").innerHTML=state.receipts.length?state.receipts.map(r=>`<tr><td>${esc(r.receipt_number)}</td><td>${esc(r.payment_number)}</td><td>${esc(r.receipt_date)}</td><td>${money(r.amount)}</td><td><button class="payment-detail-link" data-register-receipt="${r.id}">View / PDF</button></td></tr>`).join(''):'<tr><td colspan="5"><strong>No receipts yet</strong></td></tr>';
    document.querySelectorAll('[data-register-allocation]').forEach(b=>b.onclick=()=>showAllocationDetail(b.dataset.registerAllocation));document.querySelectorAll('[data-register-receipt]').forEach(b=>b.onclick=()=>showReceiptDetail(b.dataset.registerReceipt));
  }
  async function refresh(){const body=$("[data-payment-rows]");try{[state.payments,state.allocations,state.receipts]=await Promise.all([all(listUrl()),all(E.allocations),all(E.receipts)]);render();renderRegisters()}catch(e){body.innerHTML=`<tr class="empty-row"><td colspan="8"><b>Could not load payments</b><span>${esc(e.message)}</span></td></tr>`}}
  async function loadParties(){const [clients,suppliers,employees,contractors]=await Promise.all([all(E.clients),all(E.suppliers),all(E.employees),all(E.contractors)]);$("[name=client]").innerHTML='<option value="">Select client</option>'+clients.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('');$("[name=supplier]").innerHTML='<option value="">Select supplier</option>'+suppliers.map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('');$("[name=employee_id]").innerHTML='<option value="">Select employee</option>'+employees.filter(x=>x.employment_status==='ACTIVE').map(x=>`<option value="${x.id}">${esc(x.name)}${x.employee_number?` — ${esc(x.employee_number)}`:''}</option>`).join('');$("[name=contractor_id]").innerHTML='<option value="">Select contractor</option>'+contractors.filter(x=>x.status==='ACTIVE').map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join('')}
  function directionFields(){const form=$("[data-payment-form]"),type=form.dataset.payeeType;['client','supplier','employee_id','contractor_id'].forEach(name=>{const field=$(`[data-${name.replace('_id','')}-field]`),input=$(`[name=${name}]`),active=name.replace('_id','').toUpperCase()===type;field.hidden=!active;input.required=active;if(!active)input.value=''})}
  function showError(type,e){const n=$(`[data-${type}-error]`);n.textContent=e.message;n.hidden=false}
  async function openPayment(type){const form=$("[data-payment-form]");form.reset();form.dataset.payeeType=type;form.elements.direction.value=type==='CLIENT'?'INCOMING':'OUTGOING';form.elements.payment_date.value=new Date().toISOString().slice(0,10);const labels={CLIENT:['Receive payment from client','Record money received from a client.'],SUPPLIER:['Pay supplier','Record money paid to a supplier.'],EMPLOYEE:['Pay employee','Record a direct wage, salary, or reimbursement payment.'],CONTRACTOR:['Pay contractor','Record a direct contractor or subcontractor payment.']};$("[data-payment-form-title]").textContent=labels[type][0];$("[data-payment-form-context]").textContent=labels[type][1];directionFields();$("[data-payment-error]").hidden=true;$("[data-payment-dialog]").showModal();try{await loadParties()}catch(e){showError('payment',e)}}
  async function submitPayment(event){event.preventDefault();const values=Object.fromEntries(new FormData(event.currentTarget));['client','supplier','employee_id','contractor_id','reference','notes','payment_number'].forEach(k=>{if(!values[k])delete values[k]});try{await api(E.payments,{method:'POST',body:JSON.stringify(values)});$("[data-payment-dialog]").close();await refresh()}catch(e){showError('payment',e)}}
  async function openAllocation(id){
    const payment=state.payments.find(p=>p.id===id),form=$("[data-allocation-form]");form.reset();form.elements.payment.value=id;$("[data-allocation-title]").textContent=`Allocate ${payment.payment_number}`;$("[data-allocation-error]").hidden=true;$("[data-allocation-dialog]").showModal();
    const byParty={CLIENT:{endpoint:E.clientInvoices,match:i=>i.client===payment.client},SUPPLIER:{endpoint:E.supplierInvoices,match:i=>i.supplier===payment.supplier},CONTRACTOR:{endpoint:E.contractorInvoices,match:i=>i.contractor_id===payment.contractor_id}};
    const cfg=byParty[payment.payee_type];
    try{const invoices=(await all(cfg.endpoint)).filter(i=>['SENT','OVERDUE','PARTIALLY_PAID'].includes(i.status)&&cfg.match(i));form.elements.invoice.innerHTML='<option value="">Select invoice</option>'+invoices.map(i=>`<option value="${i.id}">${esc(i.invoice_number)} — ${money(i.outstanding_balance)} outstanding</option>`).join('');form.elements.allocated_amount.max=payment.unallocated_amount}catch(e){showError('allocation',e)}
  }
  async function submitAllocation(event){event.preventDefault();const f=event.currentTarget,p=state.payments.find(x=>x.id===f.elements.payment.value),payload={payment:f.elements.payment.value,allocated_amount:f.elements.allocated_amount.value};payload[p.payee_type==='CLIENT'?'client_invoice':p.payee_type==='CONTRACTOR'?'contractor_invoice':'supplier_invoice']=f.elements.invoice.value;try{await api(E.allocations,{method:'POST',body:JSON.stringify(payload)});$("[data-allocation-dialog]").close();await refresh()}catch(e){showError('allocation',e)}}
  function issueReceipt(id){const p=state.payments.find(x=>x.id===id),form=$("[data-receipt-form]");form.reset();form.elements.payment.value=id;form.elements.receipt_number.value=`RCT-${p.payment_number}`;form.elements.receipt_date.value=new Date().toISOString().slice(0,10);form.elements.amount.value=p.amount;$("[data-receipt-title]").textContent=`Receipt for ${p.payment_number}`;$("[data-receipt-error]").hidden=true;$("[data-receipt-dialog]").showModal()}
  async function submitReceipt(event){event.preventDefault();const values=Object.fromEntries(new FormData(event.currentTarget));if(!values.reference)delete values.reference;try{await api(E.receipts,{method:'POST',body:JSON.stringify(values)});$("[data-receipt-dialog]").close();await refresh()}catch(e){showError('receipt',e)}}
  async function openPaymentDetail(id){
    const dialog=$("[data-payment-detail-dialog]");dialog.showModal();$("[data-payment-detail-fields]").innerHTML='Loading payment…';$("[data-payment-detail-allocations]").innerHTML='Loading allocations…';$("[data-payment-detail-receipt]").textContent='Loading receipt…';
    try{
      const [p,allocations,receipts]=await Promise.all([api(`${E.payments}${id}/`),all(`${E.allocations}?payment=${id}`),all(`${E.receipts}?payment=${id}`)]);
      $("[data-payment-detail-title]").textContent=p.payment_number;
      const fields=[['Direction',p.direction],['Payee type',p.payee_type||'—'],['Partner / payee',p.payee_name||'—'],['Date',p.payment_date],['Method',p.payment_method],['Amount',money(p.amount)],['Unallocated',p.allocatable?money(p.unallocated_amount):'Not applicable'],['Reference',p.reference||'—'],['Notes',p.notes||'—'],['Created',p.created_at]];
      $("[data-payment-detail-fields]").innerHTML=fields.map(([label,value])=>`<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('');
      $("[data-payment-detail-allocations]").innerHTML=allocations.length?`<table><thead><tr><th>Invoice type</th><th>Amount</th><th>Record</th></tr></thead><tbody>${allocations.map(a=>`<tr><td>${a.client_invoice?'Client invoice':a.supplier_invoice?'Supplier invoice':'Contractor invoice'}</td><td>${money(a.allocated_amount)}</td><td><button class="payment-detail-link" data-allocation-detail="${a.id}">View ${esc(a.id.slice(0,8))}</button></td></tr>`).join('')}</tbody></table>`:'<p>No allocations recorded.</p>';
      $("[data-payment-detail-receipt]").innerHTML=receipts.length?`<button class="payment-detail-link" data-receipt-detail="${receipts[0].id}">${esc(receipts[0].receipt_number)} — ${money(receipts[0].amount)}</button>`:'No receipt issued.';
      dialog.querySelectorAll('[data-allocation-detail]').forEach(b=>b.onclick=()=>showAllocationDetail(b.dataset.allocationDetail));dialog.querySelectorAll('[data-receipt-detail]').forEach(b=>b.onclick=()=>showReceiptDetail(b.dataset.receiptDetail));
    }catch(e){$("[data-payment-detail-fields]").innerHTML=`<p class="form-error">${esc(e.message)}</p>`}
  }
  async function showAllocationDetail(id){try{const a=await api(`${E.allocations}${id}/`);alert(`Allocation ${a.id}\nAmount: ${money(a.allocated_amount)}\nInvoice: ${a.client_invoice||a.supplier_invoice}`)}catch(e){alert('Could not load allocation: '+e.message)}}
  async function showReceiptDetail(id){
    const dialog=$("[data-receipt-preview-dialog]");
    const details=$("[data-receipt-preview-details]");
    dialog.showModal();details.innerHTML='Loading receipt…';$("[data-receipt-preview-title]").textContent='Receipt preview';
    try{
      const r=await api(`${E.receipts}${id}/`);
      const party=r.payee_name||r.client_name||r.supplier_name||r.contractor_name||r.employee_name||'—';
      $("[data-receipt-preview-title]").textContent=r.receipt_number;
      const fields=[
        ['Receipt number',r.receipt_number],['Issue date',r.receipt_date],['Payment',r.payment_number],
        ['Party',party],['Payment method',r.payment_method],['Amount',money(r.amount)],
        ['Reference',r.reference||'—'],
      ];
      details.innerHTML=`<div class="receipt-preview-grid">${fields.map(([label,value])=>`<div><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`).join('')}</div>`;
      $("[data-receipt-preview-meta]").textContent=`${r.receipt_number} · ${r.receipt_date}`;
      $("[data-receipt-preview-download]").href=`${E.receipts}${id}/download/`;
    }catch(e){details.innerHTML=`<p class="form-error">${esc(e.message)}</p>`}
  }
  document.addEventListener('DOMContentLoaded',()=>{document.querySelectorAll('[data-payment-new]').forEach(button=>button.onclick=()=>openPayment(button.dataset.paymentNew));$("[data-payment-form]").onsubmit=submitPayment;$("[data-allocation-form]").onsubmit=submitAllocation;$("[data-receipt-form]").onsubmit=submitReceipt;document.querySelectorAll('[data-dialog-close]').forEach(b=>b.onclick=()=>$("[data-payment-dialog]").close());document.querySelectorAll('[data-allocation-close]').forEach(b=>b.onclick=()=>$("[data-allocation-dialog]").close());document.querySelectorAll('[data-receipt-close]').forEach(b=>b.onclick=()=>$("[data-receipt-dialog]").close());$("[data-payment-detail-close]").onclick=()=>$("[data-payment-detail-dialog]").close();document.querySelectorAll("[data-receipt-preview-close]").forEach(b=>b.onclick=()=>$("[data-receipt-preview-dialog]").close());let timer;$("[data-payment-search]").oninput=e=>{state.search=e.target.value.trim();clearTimeout(timer);timer=setTimeout(refresh,300)};$("[data-direction-filter]").onchange=e=>{state.direction=e.target.value;refresh()};$("[data-ordering]").onchange=e=>{state.ordering=e.target.value;refresh()};refresh()});
})();
