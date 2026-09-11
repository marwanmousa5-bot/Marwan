/**
 * Map icons drawn to a canvas at runtime.
 *
 * Generating them here rather than shipping sprite files keeps the icon
 * colour tied to the same status palette the rest of the UI uses, and avoids
 * a second network round-trip before the first marker can paint.
 */

function canvas(size: number): { ctx: CanvasRenderingContext2D; el: HTMLCanvasElement } {
  const el = document.createElement("canvas");
  el.width = size;
  el.height = size;
  const ctx = el.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D context unavailable");
  return { ctx, el };
}

/**
 * An arrow pointing "up" in icon space. MapLibre rotates it by the vehicle's
 * heading, so the marker shows direction of travel (Section 4b).
 */
export function vehicleArrow(color: string, size = 44): ImageData {
  const { ctx } = canvas(size);
  const c = size / 2;

  ctx.beginPath();
  ctx.arc(c, c, size * 0.36, 0, Math.PI * 2);
  ctx.fillStyle = "rgba(18, 20, 23, 0.85)";
  ctx.fill();
  ctx.lineWidth = size * 0.055;
  ctx.strokeStyle = color;
  ctx.stroke();

  ctx.beginPath();
  ctx.moveTo(c, c - size * 0.24);
  ctx.lineTo(c + size * 0.16, c + size * 0.2);
  ctx.lineTo(c, c + size * 0.1);
  ctx.lineTo(c - size * 0.16, c + size * 0.2);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();

  return ctx.getImageData(0, 0, size, size);
}

/**
 * POI pins are a different shape from vehicles on purpose: at a glance a
 * fixed location must never be mistaken for a moving one (Section 4d).
 */
export function poiPin(color: string, size = 40): ImageData {
  const { ctx } = canvas(size);
  const c = size / 2;

  ctx.beginPath();
  ctx.moveTo(c, size * 0.92);
  ctx.lineTo(c - size * 0.26, size * 0.42);
  ctx.lineTo(c + size * 0.26, size * 0.42);
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();

  ctx.beginPath();
  ctx.roundRect(c - size * 0.3, size * 0.08, size * 0.6, size * 0.38, size * 0.1);
  ctx.fillStyle = color;
  ctx.fill();

  ctx.beginPath();
  ctx.arc(c, size * 0.27, size * 0.11, 0, Math.PI * 2);
  ctx.fillStyle = "#121417";
  ctx.fill();

  return ctx.getImageData(0, 0, size, size);
}

/** Task destinations, added in Phase 3, get their own square marker. */
export function destinationMarker(color: string, size = 36): ImageData {
  const { ctx } = canvas(size);
  const c = size / 2;
  ctx.translate(c, c);
  ctx.rotate(Math.PI / 4);
  ctx.fillStyle = color;
  ctx.fillRect(-size * 0.2, -size * 0.2, size * 0.4, size * 0.4);
  ctx.rotate(-Math.PI / 4);
  ctx.translate(-c, -c);
  return ctx.getImageData(0, 0, size, size);
}

export const POI_COLORS: Record<string, string> = {
  depot: "#1E90FF",
  customer_site: "#9B7BFF",
  fuel_station: "#F5A623",
  custom: "#B9C0CC",
};
