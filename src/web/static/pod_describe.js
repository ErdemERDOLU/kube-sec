// Pod Describe Modal JS
async function describePod(namespace, name) {
  const btn = event.target;
  btn.disabled = true;
  btn.innerHTML = 'Yükleniyor...';
  try {
    const resp = await fetch(`/k8s-explorer/describe?type=pod&namespace=${encodeURIComponent(namespace)}&name=${encodeURIComponent(name)}`);
    const data = await resp.json();
    let describeText = data.describe || data.error || 'Describe verisi alınamadı.';
    document.getElementById('describeModalLabel').textContent = `Pod Describe: ${namespace}/${name}`;
    document.getElementById('describeModalBody').textContent = describeText;
    var modal = new bootstrap.Modal(document.getElementById('describeModal'));
    modal.show();
  } catch (e) {
    alert('Describe alınamadı: ' + e);
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Describe';
  }
}
