// Metro configuration for Expo SDK 57. Extends the default Expo Metro
// config with NativeWind's CSS transformer so Tailwind classNames compile
// to React Native styles.

const { getDefaultConfig } = require("expo/metro-config");
const { withNativeWind } = require("nativewind/metro");

const config = getDefaultConfig(__dirname);

module.exports = withNativeWind(config, { input: "./global.css" });
