(function () {
  "use strict";
  var PAGE_SIZE = 10;

  function getPairedIds(container) {
    var ids = {};
    Array.prototype.forEach.call(container.querySelectorAll("tr[data-pair-id]"), function (r) {
      ids[r.getAttribute("data-pair-id")] = true;
    });
    return ids;
  }

  // คืนแถวข้อมูลปัจจุบันของตาราง (ไม่รวมแถวหัวตาราง, แถวย่อยของฟอร์มแก้ไข, และแถว "ไม่พบรายการ" ที่สคริปต์นี้แทรกเอง)
  // ดึงใหม่ทุกครั้งที่เรียก (ไม่ cache ลำดับ) เพราะ sortable.js อาจสลับตำแหน่งแถวใน DOM จริงไปแล้วหลังผู้ใช้กดเรียงลำดับ
  function getDataRows(table, pairedIds) {
    return Array.prototype.slice.call(table.rows).slice(1).filter(function (r) {
      return !(r.id && pairedIds[r.id]) && !r.classList.contains("js-search-empty-row");
    });
  }

  function setupTable(table) {
    var headerRow = table.rows[0];
    if (!headerRow) return;
    var container = headerRow.parentNode;
    var pairedIds = getPairedIds(container);
    var initialCount = getDataRows(table, pairedIds).length;

    // ค้นหาแบบพิมพ์แล้วกรองทันที: ผูกกับ <input data-search-for="TABLE_ID"> ถ้ามี (TABLE_ID ต้องตรงกับ id ของตารางนี้)
    var searchInput = table.id ? document.querySelector('input[data-search-for="' + table.id + '"]') : null;

    if (initialCount <= PAGE_SIZE && !searchInput) return; // แถวน้อย และไม่มีช่องค้นหา ไม่ต้องทำอะไรเพิ่ม (พฤติกรรมเดิม)

    var state = { page: 1, query: "" };

    function totalPages(rows) {
      return Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    }

    var pager = null, prevBtn, nextBtn, label;
    if (initialCount > PAGE_SIZE) {
      pager = document.createElement("div");
      pager.className = "pager-controls";

      prevBtn = document.createElement("button");
      prevBtn.type = "button";
      prevBtn.className = "btn small secondary";
      prevBtn.textContent = "‹ ก่อนหน้า";
      prevBtn.addEventListener("click", function () {
        state.page -= 1;
        render();
      });

      label = document.createElement("span");
      label.className = "pager-label";

      nextBtn = document.createElement("button");
      nextBtn.type = "button";
      nextBtn.className = "btn small secondary";
      nextBtn.textContent = "ถัดไป ›";
      nextBtn.addEventListener("click", function () {
        state.page += 1;
        render();
      });

      pager.appendChild(prevBtn);
      pager.appendChild(label);
      pager.appendChild(nextBtn);
      table.insertAdjacentElement("afterend", pager);
    }

    // แถวข้อความ "ไม่พบรายการที่ค้นหา" — สร้างไว้เผื่อใช้ ซ่อนอยู่จนกว่าจะค้นหาแล้วไม่เจอ
    var emptyRow = document.createElement("tr");
    emptyRow.className = "js-search-empty-row";
    emptyRow.style.display = "none";
    var emptyCell = document.createElement("td");
    emptyCell.colSpan = headerRow.cells.length;
    emptyCell.textContent = "ไม่พบรายการที่ตรงกับคำค้นหา";
    emptyRow.appendChild(emptyCell);
    container.appendChild(emptyRow);

    function render() {
      var allRows = getDataRows(table, pairedIds); // ดึงลำดับล่าสุดเสมอ เผื่อเพิ่งถูกเรียงลำดับใหม่
      var rows = state.query
        ? allRows.filter(function (row) { return row.textContent.toLowerCase().indexOf(state.query) !== -1; })
        : allRows;
      var pages = totalPages(rows);
      if (state.page > pages) state.page = pages;
      if (state.page < 1) state.page = 1;
      var start = (state.page - 1) * PAGE_SIZE;
      var end = start + PAGE_SIZE;

      allRows.forEach(function (row) {
        var idx = rows.indexOf(row);
        var visible = idx !== -1 && (rows.length <= PAGE_SIZE || (idx >= start && idx < end));
        row.style.display = visible ? "" : "none";
        var pairId = row.getAttribute("data-pair-id");
        if (pairId && !visible) {
          // แถวที่ถูกซ่อนเพราะเปลี่ยนหน้า/ค้นหาไม่เจอ ต้องบังคับซ่อนแถวแก้ไข (edit-toggle) คู่กันด้วยเสมอ
          var pairedRow = document.getElementById(pairId);
          if (pairedRow) pairedRow.style.display = "none";
        }
      });

      container.appendChild(emptyRow); // sortable.js ย้ายแถวอื่นไปต่อท้ายเวลาคลิกเรียงลำดับ ต้องดันแถวนี้ไปท้ายสุดเสมอกันหลุดตำแหน่ง
      emptyRow.style.display = rows.length === 0 ? "" : "none";

      if (pager) {
        if (rows.length <= PAGE_SIZE) {
          pager.style.display = "none";
        } else {
          pager.style.display = "";
          label.textContent = "หน้า " + state.page + " จาก " + pages + " (ทั้งหมด " + rows.length + " รายการ)";
          prevBtn.disabled = state.page <= 1;
          nextBtn.disabled = state.page >= pages;
        }
      }
    }

    if (searchInput) {
      searchInput.addEventListener("input", function () {
        state.query = searchInput.value.trim().toLowerCase();
        state.page = 1;
        render();
      });
    }

    // sortable.js เรียงข้อมูลใหม่ทั้งชุดเสมอ (ไม่ใช่แค่หน้าปัจจุบัน) — พอเรียงเสร็จให้กลับไปหน้า 1
    // เพื่อให้ผู้ใช้เห็นผลการเรียงลำดับตั้งแต่รายการแรกทันที
    Array.prototype.forEach.call(headerRow.querySelectorAll("th.sortable-th"), function (th) {
      th.addEventListener("click", function () {
        state.page = 1;
        render();
      });
    });

    render();
  }

  document.addEventListener("DOMContentLoaded", function () {
    var tables = document.querySelectorAll("table.sortable");
    Array.prototype.forEach.call(tables, setupTable);
  });
})();
