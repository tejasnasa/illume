// Metro configuration for Expo SDK 57.
//
// NativeWind v5 discovers ``global.css`` from the app entry point that
// imports it; the v4 ``input`` option is no longer needed.
const { getDefaultConfig } = require("expo/metro-config");
const { withNativeWind } = require("nativewind/metro");

const config = getDefaultConfig(__dirname);

module.exports = withNativeWind(config);
