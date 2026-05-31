type NumericLike = number | null | undefined

// Helper: quantile line
function quantile(arr: NumericLike[], q: number): Array<number | null> {
    const sorted = arr
        .filter((v): v is number => typeof v === 'number' && !Number.isNaN(v))
        .sort((a, b) => a - b)
    if (!sorted.length) return []
    const pos = (sorted.length - 1) * q
    const base = Math.floor(pos)
    const rest = pos - base
    const qVal = sorted[base + 1] !== undefined
        ? sorted[base] + rest * (sorted[base + 1] - sorted[base])
        : sorted[base]
    const roundedQVal = Math.round(qVal * 100) / 100
    return arr.map((v) => (typeof v !== 'number' || Number.isNaN(v)) ? null : roundedQVal)
}

type OHLC = { high: number; low: number; close: number }

function calculateATR(data: OHLC[], period = 14): Array<number | null> {
    // data: [{high, low, close}, ...] 按时间升序
    const trList = [];
    for (let i = 0; i < data.length; i++) {
        const high = data[i].high;
        const low = data[i].low;
        const prevClose = i > 0 ? data[i - 1].close : data[i].close;
        const tr = Math.max(
            high - low,
            Math.abs(high - prevClose),
            Math.abs(low - prevClose)
        );
        trList.push(tr);
    }
    // 计算ATR
    const atrList = [];
    for (let i = 0; i < trList.length; i++) {
        if (i < period - 1) {
            atrList.push(null); // 前period-1天无ATR
        } else {
            const atr = trList.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0) / period;
            atrList.push(atr);
        }
    }
    return atrList;

}
export { quantile, calculateATR }