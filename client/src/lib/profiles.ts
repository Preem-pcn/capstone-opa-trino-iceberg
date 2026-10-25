/* ---------- illustrative (schematic) profiles — NOT recorded data ---------- */
type Points = [number, number][];

export function interp(pts: Points, t: number) {
  if (t <= pts[0][0]) return pts[0][1];
  for (let i = 1; i < pts.length; i++) {
    if (t <= pts[i][0]) { const [t0, v0] = pts[i - 1], [t1, v1] = pts[i]; return v0 + ((v1 - v0) * (t - t0)) / (t1 - t0); }
  }
  return pts[pts.length - 1][1];
}

export const P_ALT: Points = [[0,0],[5154,0],[6794,38000],[9000,39000],[10800,41000],[12000,42348],[14200,43036],[17500,43000],[19362,42900],[20600,9000],[21251,0],[22020,0]];
export const P_GS: Points = [[0,0],[500,12],[4900,14],[5154,165],[6794,470],[12000,501],[19362,492],[20900,180],[21251,138],[21600,22],[21900,10],[22020,0]];
const P_HDG: Points = [[0,10],[5000,192],[6794,250],[12000,291.8],[19362,300],[21251,302],[22020,300]];
const P_PITCH: Points = [[0,0],[5050,0],[5154,11],[5600,14],[6794,5],[6950,2.6],[12000,2.8125],[19300,2.6],[19500,-1.8],[21100,2.4],[21240,5.5],[21400,0],[22020,0]];

export function illus(t: number) {
  const roll = (t < 6794 || t > 19362 ? 7 : 1.1) * Math.sin(t / 430) * (t < 4900 || t > 21300 ? 0.1 : 1);
  const vrtg = 1 + 0.015 * Math.sin(t / 37) + 0.277 * Math.exp(-Math.pow((t - 21251) / 6, 2)) + (t > 5100 && t < 5300 ? 0.08 * Math.sin(t / 9) : 0);
  return { alt: interp(P_ALT, t), gs: interp(P_GS, t), hdg: ((interp(P_HDG, t) % 360) + 360) % 360, pitch: interp(P_PITCH, t), roll, vrtg };
}

export interface Sample { alt: number; gs: number; hdg: number; pitch: number; roll: number; vrtg: number; src: 'demo' }

// v3 cockpit plays the schematic profile at every offset, labelled as demo data.
export const valuesAt = (t: number): Sample => ({ ...illus(t), src: 'demo' });
