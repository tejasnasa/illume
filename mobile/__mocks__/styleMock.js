/**
 * Style mock for the jest test environment.
 *
 * The root layout imports ``../global.css`` so NativeWind's runtime
 * registers its class registry when the app starts. On device, Metro
 * + ``withNativeWind`` resolve that import to the bundled CSS file. In
 * jest there is no Metro hook, so we substitute an empty module -- the
 * :func:`nativewind` jest mock in ``jest.setup.js`` already returns
 * components unchanged for any ``className`` prop, so the CSS values
 * are not needed.
 */
module.exports = {};
