document.querySelectorAll('.flash').forEach((item)=>setTimeout(()=>item.remove(),5000));
document.querySelectorAll('.flash').forEach((item)=>setTimeout(()=>item.remove(),5000));

document.querySelectorAll('.js-toggle').forEach((button) => {
  button.addEventListener('click', () => {
    const target = document.getElementById(button.dataset.target);
    if (target) target.classList.toggle('is-open');
  });
});

const orderItems = document.getElementById('order-items');
function refreshOrderTotals() {
  let total = 0;
  document.querySelectorAll('.order-line').forEach((line) => {
    const select = line.querySelector('[data-product-select]');
    const option = select?.selectedOptions?.[0];
    const price = Number(option?.dataset.price || 0);
    const qty = Math.max(1, parseInt(line.querySelector('input[name="quantity"]')?.value || '1', 10));
    const lineTotal = price * qty;
    total += lineTotal;
    const info = line.querySelector('[data-product-info]');
    const lineTotalInput = line.querySelector('[data-line-total]');
    if (info) info.value = option?.value ? `${option.dataset.article || 'Artikulsiz'} / ${option.dataset.color || '-'} / ${option.dataset.size || '-'}` : '';
    if (lineTotalInput) lineTotalInput.value = lineTotal ? lineTotal.toLocaleString('uz-UZ') : '';
  });
  const totalNode = document.querySelector('[data-order-total]');
  if (totalNode) totalNode.textContent = total.toLocaleString('uz-UZ');
}
if (orderItems) {
  orderItems.addEventListener('input', refreshOrderTotals);
  orderItems.addEventListener('change', refreshOrderTotals);
  document.querySelector('[data-add-order-line]')?.addEventListener('click', () => {
    const firstLine = orderItems.querySelector('.order-line');
    const clone = firstLine.cloneNode(true);
    clone.querySelectorAll('input').forEach((input) => input.value = input.name === 'quantity' ? '1' : '');
    clone.querySelector('select').selectedIndex = 0;
    orderItems.appendChild(clone);
  });
  refreshOrderTotals();
}

document.querySelector('[data-customer-select]')?.addEventListener('change', (event) => {
  const option = event.target.selectedOptions[0];
  const form = event.target.form;
  if (!option?.value || !form) return;
  form.elements.customer_name.value = option.dataset.name || '';
  form.elements.customer_phone.value = option.dataset.phone || '';
  if (form.elements.telegram) form.elements.telegram.value = option.dataset.telegram || '';
  if (form.elements.instagram) form.elements.instagram.value = option.dataset.instagram || '';
});