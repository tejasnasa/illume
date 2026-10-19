// Babel configuration for Expo SDK 57.
//
// NativeWind v5 no longer ships its own preset: ``babel-preset-expo``
// alone compiles ``className`` to React Native styles via the
// ``react-native-css`` engine. The v4 ``nativewind/babel`` preset and
// the ``jsxImportSource: "nativewind"`` option have both been removed.
module.exports = function (api) {
  api.cache(true);
  return {
    presets: ["babel-preset-expo"],
  };
};
