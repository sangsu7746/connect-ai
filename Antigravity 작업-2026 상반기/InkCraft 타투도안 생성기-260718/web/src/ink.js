// 도안 배경 제거 유틸 — 흑백 타투 도안의 흰 종이 배경을 투명으로 바꾼다.
// 밝기를 역알파로 쓰는 방식이라 안티앨리어싱 선 가장자리가 자연스럽게 유지된다.
// 전부 클라이언트 캔버스 연산이라 서버 비용 0원.

export function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('Failed to load image.'));
    img.src = src;
  });
}

/** 파일 → 리사이즈된 JPEG dataURL (최대 변 maxSide, 비용·용량 절약) */
export function fileToDataUrl(file, maxSide = 1280) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      const ratio = Math.min(1, maxSide / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = Math.round(img.width * ratio);
      c.height = Math.round(img.height * ratio);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      resolve(c.toDataURL('image/jpeg', 0.92));
    };
    img.onerror = () => reject(new Error('Failed to read the photo.'));
    img.src = url;
  });
}

/** dataURL 도안 → 흰 배경이 투명해진 PNG dataURL */
export async function removeWhiteBg(designSrc) {
  const img = await loadImage(designSrc);
  const c = document.createElement('canvas');
  c.width = img.width;
  c.height = img.height;
  const x = c.getContext('2d');
  x.drawImage(img, 0, 0);
  const data = x.getImageData(0, 0, c.width, c.height);
  const p = data.data;
  for (let i = 0; i < p.length; i += 4) {
    // '흰색에서 얼마나 먼가'를 알파로 사용 — 흑백뿐 아니라 컬러 잉크(노랑 등 고휘도 색)도 유지된다.
    // JPEG 노이즈로 남는 희미한 사각 패치를 없애기 위해 흰색 근처(20 미만)는 완전 투명 처리.
    const dist = Math.max(255 - p[i], 255 - p[i + 1], 255 - p[i + 2]);
    p[i + 3] = dist < 20 ? 0 : Math.min(255, Math.round(dist * 1.12));
  }
  x.putImageData(data, 0, 0);
  return c.toDataURL('image/png');
}
