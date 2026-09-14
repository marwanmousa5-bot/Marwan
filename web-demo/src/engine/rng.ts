/** Deterministic RNG so every visitor sees the same demo fleet. */
export class Rng {
  private s: number;
  constructor(seed = 0x5eed1e) { this.s = seed >>> 0; }

  next(): number {
    // mulberry32
    this.s = (this.s + 0x6d2b79f5) >>> 0;
    let t = this.s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  int(min: number, max: number): number {
    return Math.floor(this.next() * (max - min + 1)) + min;
  }

  float(min: number, max: number): number {
    return this.next() * (max - min) + min;
  }

  pick<T>(arr: readonly T[]): T {
    return arr[Math.floor(this.next() * arr.length)];
  }

  pickMany<T>(arr: readonly T[], n: number): T[] {
    const pool = [...arr];
    const out: T[] = [];
    while (out.length < n && pool.length) {
      out.push(pool.splice(Math.floor(this.next() * pool.length), 1)[0]);
    }
    return out;
  }

  chance(p: number): boolean {
    return this.next() < p;
  }

  shuffle<T>(arr: T[]): T[] {
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(this.next() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
  }
}

export function uid(prefix: string, n: number): string {
  return `${prefix}_${n.toString(36).padStart(5, '0')}`;
}
