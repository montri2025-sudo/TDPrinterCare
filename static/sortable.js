// เรียงลำดับตารางได้ด้วยการคลิกหัวตาราง — ใช้ได้กับตารางที่มี class="sortable"
// ไม่ต้องพึ่งไลบรารีภายนอก (เขียนด้วย vanilla JS ล้วน สอดคล้องกับสไตล์ของแอปนี้)
//
// รองรับแถวที่มี "แถวฟอร์มแก้ไขที่ซ่อนอยู่" ตามหลัง (เช่น ปุ่ม "แก้ไข" ที่กดแล้วโชว์แถวฟอร์ม
// ด้านล่าง) โดยใส่ attribute data-pair-id="<id ของแถวฟอร์มนั้น>" ไว้ที่แถวหลัก แถวคู่กันจะถูก
// ย้ายตามกันเสมอเวลาเรียงลำดับใหม่ ไม่มีวันหลุดจากกัน
(function () {
  "use strict";

  function cellText(row, idx) {
    var cell = row.children[idx];
    return cell ? cell.textContent.trim() : "";
  }

  function parseNumeric(text) {
    var cleaned = text.replace(/[,\s฿%]/g, "");
    if (cleaned === "" || isNaN(cleaned)) return null;
    return parseFloat(cleaned);
  }

  function compareValues(a, b) {
    var na = parseNumeric(a);
    var nb = parseNumeric(b);
    if (na !== null && nb !== null) return na - nb;
    return a.localeCompare(b, "th");
  }

  function clearIndicators(headerRow) {
    Array.prototype.forEach.call(headerRow.cells, function (cell) {
      cell.removeAttribute("data-sort-dir");
      var ind = cell.querySelector(".sort-indicator");
      if (ind) ind.textContent = "⇅"; // ⇅
    });
  }

  function makeSortable(table) {
    var rows = Array.prototype.slice.call(table.rows);
    if (rows.length < 2) return;
    var headerRow = rows[0];
    var container = headerRow.parentNode;

    Array.prototype.forEach.call(headerRow.cells, function (th, idx) {
      if (!th.textContent.trim()) return; // คอลัมน์ปุ่ม/ว่าง ไม่ต้องเรียงลำดับ
      if (th.hasAttribute("data-no-sort")) return;

      th.classList.add("sortable-th");
      th.setAttribute("title", "คลิกเพื่อเรียงลำดับ");
      var indicator = document.createElement("span");
      indicator.className = "sort-indicator";
      indicator.textContent = "⇅";
      th.appendChild(indicator);

      th.addEventListener("click", function () {
        var dataRows = Array.prototype.slice.call(table.rows).slice(1).filter(function (row) {
          return !row.classList.contains("js-search-empty-row"); // ไม่ใช่แถวจริง (paginate.js แทรกไว้แสดงตอนค้นหาไม่เจอ) ไม่ต้องเรียงลำดับ
        });
        var pairedIds = {};
        var units = [];
        dataRows.forEach(function (row) {
          if (pairedIds[row.id]) return; // แถวนี้ถูกจับคู่ไปกับแถวก่อนหน้าแล้ว ข้าม
          var pairId = row.getAttribute("data-pair-id");
          var pairedRow = null;
          if (pairId) {
            pairedRow = document.getElementById(pairId);
            if (pairedRow) pairedIds[pairedRow.id] = true;
          }
          units.push({ main: row, paired: pairedRow });
        });

        var asc = th.getAttribute("data-sort-dir") !== "asc";
        units.sort(function (u1, u2) {
          var cmp = compareValues(cellText(u1.main, idx), cellText(u2.main, idx));
          return asc ? cmp : -cmp;
        });

        clearIndicators(headerRow);
        th.setAttribute("data-sort-dir", asc ? "asc" : "desc");
        var ind = th.querySelector(".sort-indicator");
        if (ind) ind.textContent = asc ? "▲" : "▼"; // ▲ / ▼

        units.forEach(function (u) {
          container.appendChild(u.main);
          if (u.paired) container.appendChild(u.paired);
        });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var tables = document.querySelectorAll("table.sortable");
    Array.prototype.forEach.call(tables, makeSortable);
  });
})();
