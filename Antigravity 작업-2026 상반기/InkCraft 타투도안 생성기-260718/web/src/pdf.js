// 플래시 시트(PDF) 조립 — 클라이언트에서 jsPDF로 생성 (서버 비용 0원)
// A4 세로, 표지(한글 지원을 위해 캔버스로 렌더링) + 도안들 + 하단 푸터.
import { jsPDF } from 'jspdf';

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Failed to load design image.'));
    img.src = src;
  });
}

/** 표지 — jsPDF 기본 폰트는 한글 미지원이라 캔버스로 그려서 이미지로 넣는다 */
async function makeCover(title, thumbSrc) {
  const W = 1240, H = 1754; // A4 @150dpi
  const c = document.createElement('canvas');
  c.width = W; c.height = H;
  const x = c.getContext('2d');

  x.fillStyle = '#f7f4ee';
  x.fillRect(0, 0, W, H);

  // 빈티지 플래시 시트 느낌의 이중 잉크 테두리
  x.strokeStyle = '#17161a';
  x.lineJoin = 'miter';
  x.lineWidth = 10;
  x.strokeRect(50, 50, W - 100, H - 100);
  x.lineWidth = 3;
  x.strokeRect(74, 74, W - 148, H - 148);

  x.fillStyle = '#17161a';
  x.textAlign = 'center';
  x.font = '700 44px Georgia, serif';
  x.fillText('🖋️ InkCraft — Tattoo Flash', W / 2, 190);

  // 제목 (길면 자동 축소)
  let size = 96;
  x.font = `800 ${size}px Georgia, serif`;
  while (x.measureText(title).width > W - 240 && size > 40) {
    size -= 4;
    x.font = `800 ${size}px Georgia, serif`;
  }
  x.fillText(title, W / 2, 330);

  if (thumbSrc) {
    const img = await loadImage(thumbSrc);
    const s = 780;
    x.save();
    x.shadowColor = 'rgba(0,0,0,0.25)';
    x.shadowBlur = 30;
    x.shadowOffsetY = 12;
    x.fillStyle = '#ffffff';
    x.fillRect((W - s) / 2 - 20, 430, s + 40, s + 40);
    x.restore();
    x.drawImage(img, (W - s) / 2, 450, s, s);
    x.strokeStyle = '#17161a';
    x.lineWidth = 4;
    x.strokeRect((W - s) / 2 - 20, 430, s + 40, s + 40);
  }

  x.fillStyle = '#6b6660';
  x.font = '400 34px Georgia, serif';
  x.fillText(new Date().toLocaleDateString(), W / 2, H - 170);
  x.font = '400 30px Georgia, serif';
  x.fillText('Print on A4 · Reference art — final stencil by your artist', W / 2, H - 110);

  return c.toDataURL('image/jpeg', 0.92);
}

/**
 * 플래시 시트 PDF 생성 후 즉시 다운로드.
 * @param {object} opt {title, pages: dataURL[], fileName}
 */
export async function buildFlashSheet({ title, pages, fileName = 'inkcraft-flash-sheet' }) {
  const doc = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'portrait' });
  const W = doc.internal.pageSize.getWidth();   // 210
  const H = doc.internal.pageSize.getHeight();  // 297

  // 표지
  const cover = await makeCover(title || 'My Flash Sheet', pages[0]);
  doc.addImage(cover, 'JPEG', 0, 0, W, H);

  // 도안들 — 정사각 이미지를 여백 두고 중앙 배치
  const margin = 14;
  const size = W - margin * 2; // 182mm
  const y = (H - size) / 2 - 8;
  pages.forEach((src, i) => {
    doc.addPage();
    doc.addImage(src, 'JPEG', margin, y, size, size);
    doc.setFontSize(10);
    doc.setTextColor(150);
    doc.text(`${i + 1} / ${pages.length}`, W / 2, H - 10, { align: 'center' });
  });

  doc.save(`${fileName}.pdf`);
}
