(() => {
  const buildCells = (table) => {
    const overlay = table.querySelector('.studio-preview-overlay');
    if (!overlay || overlay.dataset.cellsBuilt) return;
    const columns = [...overlay.querySelectorAll('.studio-preview-column')];
    const rows = [...overlay.querySelectorAll('.studio-preview-row')];
    const canonicalCells = JSON.parse(table.dataset.cells || '[]');
    const cells = document.createDocumentFragment();
    canonicalCells.forEach((source) => {
      const cell = document.createElement('span');
      cell.className = 'studio-preview-cell';
      cell.dataset.x1 = source.x1; cell.dataset.x2 = source.x2;
      cell.dataset.y1 = source.y1; cell.dataset.y2 = source.y2;
      cell.dataset.column = source.column_index; cell.dataset.row = source.row_index;
      cells.appendChild(cell);
    });
    overlay.appendChild(cells);
    overlay.dataset.cellsBuilt = '1';
    columns.forEach((column) => { column.style.display = 'none'; });
    rows.forEach((row) => { row.style.display = 'none'; });
  };
  const syncCells = (table) => {
    const roles = {};
    table.querySelectorAll('select[name="table_role"]').forEach((select) => {
      const [, column, role] = select.value.split('|');
      roles[column] = role || 'none';
    });
    const activeRows = {};
    table.querySelectorAll('input[name="table_row"]').forEach((input) => {
      activeRows[input.value.split('|')[1]] = input.checked;
    });
    table.querySelectorAll('.studio-preview-cell').forEach((cell) => {
      cell.className = `studio-preview-cell role-${roles[cell.dataset.column] || 'none'}`;
      cell.classList.toggle('role-skip', activeRows[cell.dataset.row] === false);
    });
  };
  const refresh = () => document.querySelectorAll('[data-studio-table]').forEach((table) => {
    buildCells(table);
    syncCells(table);
    const view = table.querySelector('[data-studio-preview]');
    const image = view?.querySelector('img');
    if (!view || !image?.naturalWidth) return;
    const x1 = +table.dataset.cropX1, y1 = +table.dataset.cropY1;
    const x2 = +table.dataset.cropX2, y2 = +table.dataset.cropY2;
    const scale = Math.min(Math.max(1, view.parentElement.clientWidth) / (x2 - x1), 1.1);
    view.style.width = `${(x2 - x1) * scale}px`;
    view.style.height = `${(y2 - y1) * scale}px`;
    image.style.width = `${image.naturalWidth * scale}px`;
    image.style.height = 'auto';
    image.style.left = `${-x1 * scale}px`;
    image.style.top = `${-y1 * scale}px`;
    view.querySelectorAll('.studio-preview-cell').forEach((box) => {
      box.style.left = `${(+box.dataset.x1 - x1) * scale}px`;
      box.style.top = `${(+box.dataset.y1 - y1) * scale}px`;
      box.style.width = `${(+box.dataset.x2 - +box.dataset.x1) * scale}px`;
      box.style.height = `${(+box.dataset.y2 - +box.dataset.y1) * scale}px`;
    });
  });
  document.addEventListener('change', (event) => {
    if (!event.target.matches('select[name="table_role"],input[name="table_row"]')) return;
    const table = event.target.closest('[data-studio-table]');
    if (table) syncCells(table);
  });
  window.addEventListener('load', refresh);
  window.addEventListener('resize', refresh);
  setTimeout(refresh, 0);
})();
