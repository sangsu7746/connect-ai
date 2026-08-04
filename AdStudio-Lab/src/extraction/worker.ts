// Web Worker 래퍼 — UI 블록 방지 (명세 §7)
import { extractFromBlob } from './pipeline';

interface Req { id: number; blob: Blob; name: string }

self.onmessage = async (e: MessageEvent<Req>) => {
  const { id, blob, name } = e.data;
  try {
    const result = await extractFromBlob(blob, name);
    (self as unknown as Worker).postMessage({ id, ok: true, result });
  } catch (err) {
    (self as unknown as Worker).postMessage({ id, ok: false, error: String(err) });
  }
};
