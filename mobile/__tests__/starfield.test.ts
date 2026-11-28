import { buildStars, mulberry, STAR_CELL } from "@/lib/starfield";

describe("starfield", () => {
  it("is deterministic for a given size", () => {
    expect(buildStars(360, 800)).toEqual(buildStars(360, 800));
  });

  it("returns nothing for a zero-sized screen", () => {
    expect(buildStars(0, 800)).toEqual([]);
  });

  it("snaps every star to the cell grid and keeps it on screen", () => {
    for (const star of buildStars(360, 800)) {
      expect(star.x).toBeGreaterThanOrEqual(0);
      expect(star.x).toBeLessThan(1);
      expect(star.y).toBeLessThan(1);
      const col = (star.x * 360) / STAR_CELL;
      expect(Math.abs(col - Math.round(col))).toBeLessThan(0.5);
    }
  });

  it("scales the count with the area", () => {
    expect(buildStars(720, 1600).length).toBeGreaterThan(
      buildStars(360, 800).length,
    );
  });

  it("mulberry stays in [0, 1)", () => {
    const rnd = mulberry(7);
    for (let i = 0; i < 100; i++) {
      const v = rnd();
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
  });
});
