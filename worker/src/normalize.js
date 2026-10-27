// JS port of src/tech_amharic/normalize.py. Keep the fold tables identical;
// tests/test_site.py compares them with the Python source.

export const ROW_FOLDS = { 0x1210: 0x1200, 0x1280: 0x1200, 0x1220: 0x1230, 0x12d0: 0x12a0, 0x1340: 0x1338 };
export const ORDER_FOLDS = { 0x1203: 0x1200, 0x12a3: 0x12a0 };

const DROP = /[\p{P}\p{Z}\p{C}\p{Sk}\p{Sm}]/u;

export function isEthiopicCodePoint(cp) {
  return (cp >= 0x1200 && cp <= 0x139f) || (cp >= 0x2d80 && cp <= 0x2ddf) || (cp >= 0xab00 && cp <= 0xab2f);
}

export function normKey(text) {
  let out = "";
  for (const ch of String(text).normalize("NFC").toLowerCase()) {
    if (DROP.test(ch)) continue;
    let cp = ch.codePointAt(0);
    if (isEthiopicCodePoint(cp)) {
      const row = cp & ~0x7;
      if (row in ROW_FOLDS) cp = ROW_FOLDS[row] + (cp - row);
      if (cp in ORDER_FOLDS) cp = ORDER_FOLDS[cp];
    }
    out += String.fromCodePoint(cp);
  }
  return out;
}

export function ethiopicRatio(text) {
  const letters = [...String(text)].filter((ch) => /\p{L}/u.test(ch));
  if (!letters.length) return 0;
  return letters.filter((ch) => isEthiopicCodePoint(ch.codePointAt(0))).length / letters.length;
}
