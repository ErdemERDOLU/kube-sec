/**
 * Kube-Sec ortak JS yardimci fonksiyonlari
 * Tum sayfalara base.html uzerinden yuklenir.
 * Bu dosya degistirildigi zaman tum templateler etkilenir -- dikkatli olun.
 */

/**
 * Bootstrap toast gosterir.
 * Guvenlij: message icerigi textContent ile set edilir (XSS-safe).
 * @param {string} message - Gosterilecek mesaj
 * @param {'success'|'error'|'warning'} type - Bildirim turu (varsayilan: 'success')
 * @param {number} delay - Otomatik kapanma suresi ms cinsinden (varsayilan: 3500)
 */
function showToast(message, type = 'success', delay = 3500) {
  const bg = type === 'error'   ? 'bg-danger'
           : type === 'warning' ? 'bg-warning text-dark'
           :                      'bg-success';

  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container position-fixed top-0 end-0 p-3';
    document.body.appendChild(container);
  }

  const toastEl = document.createElement('div');
  toastEl.className = `toast align-items-center text-white ${bg} border-0`;
  toastEl.setAttribute('role', 'alert');
  toastEl.setAttribute('aria-live', 'assertive');
  toastEl.setAttribute('aria-atomic', 'true');

  const inner = document.createElement('div');
  inner.className = 'd-flex';

  const body = document.createElement('div');
  body.className = 'toast-body';
  body.textContent = message;  // XSS-safe: textContent degil innerHTML

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'btn-close btn-close-white me-2 m-auto';
  closeBtn.setAttribute('data-bs-dismiss', 'toast');
  const closeLabel = (window.i18n && window.i18n['base.btn_close'] && window.i18n['base.btn_close'][window.locale || 'tr']) || 'Kapat';
  closeBtn.setAttribute('aria-label', closeLabel);

  inner.appendChild(body);
  inner.appendChild(closeBtn);
  toastEl.appendChild(inner);
  container.appendChild(toastEl);

  toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
  new bootstrap.Toast(toastEl, { delay }).show();
}

/**
 * HTML ozel karakterlerini kacirarak XSS-guvenli string dondurur.
 * null/undefined icin bos string doner.
 * Kacirilan karakterler: & < > " ' `
 * @param {*} str - Kaciri lacak deger
 * @returns {string}
 */
function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/`/g, '&#96;');
}

/**
 * Bir ISO timestamp'ten "Xs ago / Xm ago / Xh ago / Xd ago" formatinda sure dondurur.
 * @param {string|null} ts - ISO 8601 timestamp
 * @returns {string}
 */
function timeAgo(ts) {
  if (!ts) return '-';
  const diff = Math.floor((new Date() - new Date(ts)) / 1000);
  if (diff < 60)    return diff + 's ago';
  if (diff < 3600)  return Math.floor(diff / 60) + 'm ago';
  if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
  return Math.floor(diff / 86400) + 'd ago';
}

/**
 * Bir ISO timestamp'ten "Xd / Xh / Xm" formatinda sure dondurur ("ago" soneki yok).
 * @param {string|null} ts - ISO 8601 timestamp
 * @returns {string}
 */
function calculateAge(ts) {
  if (!ts) return '-';
  const diffMs = new Date() - new Date(ts);
  const d = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  const h = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
  const m = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
  if (d > 0) return d + 'd';
  if (h > 0) return h + 'h';
  return m + 'm';
}

/**
 * Dinamik Bootstrap onay modali olusturur ve gosterir.
 * Guvenlij: title ve message icerigi textContent ile set edilir (XSS-safe).
 * Modal kapandiginda DOM'dan temizlenir.
 * @param {object} options
 * @param {string} [options.title='Onay'] - Modal basligi
 * @param {string} [options.message='Emin misiniz?'] - Modal icerigi
 * @param {string} [options.confirmText='Onayla'] - Onay buton metni
 * @param {string} [options.confirmBtnClass='btn-danger'] - Onay buton CSS sinifi
 * @param {Function} [options.onConfirm] - Onaylandiginda cagrilacak fonksiyon (async destekli)
 */
function openConfirmModal({ title = 'Onay', message = 'Emin misiniz?', confirmText = 'Onayla', confirmBtnClass = 'btn-danger', onConfirm } = {}) {
  const id = 'confirmModal-' + Date.now();

  const modalEl = document.createElement('div');
  modalEl.className = 'modal fade';
  modalEl.id = id;
  modalEl.setAttribute('tabindex', '-1');

  const dialog = document.createElement('div');
  dialog.className = 'modal-dialog';

  const content = document.createElement('div');
  content.className = 'modal-content';

  // Header
  const header = document.createElement('div');
  header.className = 'modal-header';
  const titleEl = document.createElement('h5');
  titleEl.className = 'modal-title';
  titleEl.textContent = title;  // XSS-safe
  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'btn-close';
  closeBtn.setAttribute('data-bs-dismiss', 'modal');
  header.appendChild(titleEl);
  header.appendChild(closeBtn);

  // Body
  const body = document.createElement('div');
  body.className = 'modal-body';
  const msgEl = document.createElement('p');
  msgEl.className = 'mb-0';
  msgEl.textContent = message;  // XSS-safe
  body.appendChild(msgEl);

  // Footer
  const footer = document.createElement('div');
  footer.className = 'modal-footer';
  const cancelBtn = document.createElement('button');
  cancelBtn.type = 'button';
  cancelBtn.className = 'btn btn-secondary';
  cancelBtn.setAttribute('data-bs-dismiss', 'modal');
  cancelBtn.textContent = 'Iptal';
  const confirmBtn = document.createElement('button');
  confirmBtn.type = 'button';
  confirmBtn.className = 'btn ' + confirmBtnClass;
  confirmBtn.id = id + '-confirmBtn';
  confirmBtn.textContent = confirmText;
  footer.appendChild(cancelBtn);
  footer.appendChild(confirmBtn);

  content.appendChild(header);
  content.appendChild(body);
  content.appendChild(footer);
  dialog.appendChild(content);
  modalEl.appendChild(dialog);
  document.body.appendChild(modalEl);

  const modal = new bootstrap.Modal(modalEl);

  modalEl.addEventListener('hidden.bs.modal', () => {
    try { modal.dispose(); modalEl.remove(); } catch (_) {}
  });

  confirmBtn.addEventListener('click', async () => {
    const original = confirmBtn.textContent;
    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Isleniyor...';
    try {
      if (onConfirm) await onConfirm();
      modal.hide();
    } catch (e) {
      // onConfirm icindeki hatalar showToast ile kullaniciya bildirilmeli;
      // modal acik kalir.
      console.debug('confirmModal onConfirm error', e);
    } finally {
      confirmBtn.disabled = false;
      confirmBtn.textContent = original;
    }
  });

  modal.show();
}

/**
 * CSV dosyasi olusturur ve tarayici ile indirir.
 * UTF-8 BOM icerir -- Excel'de Turkce karakterlerin dogru goruntulenmesi icin zorunludur.
 * Tum hucreler cift tirnak ile sarmalanir; hucre icindeki cift tirnaklar "" ile escape edilir.
 * null / undefined degerler bos string olarak yazilir.
 * @param {string} filename - Indirilecek dosya adi (ornek: 'export.csv')
 * @param {string[]} headers - CSV baslik satiri (string dizisi)
 * @param {(string|number|null|undefined)[][]} rows - CSV veri satirlari (her satir bir dizi)
 */
function exportToCsv(filename, headers, rows) {
  function csvCell(val) {
    if (val == null) val = '';
    return '"' + String(val).replace(/"/g, '""') + '"';
  }
  const lines = [
    headers.map(csvCell).join(','),
    ...rows.map(function(row) {
      return row.map(csvCell).join(',');
    })
  ];
  // ﻿ = UTF-8 BOM -- Excel bu isaretciye gore kodlamayi dogru algilar
  const csvContent = '﻿' + lines.join('\n');
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
