/**
 * Report which native modules the Android build will link.
 *
 * Run with: `node scripts/check-native-linking.mjs`
 *
 * Two different mechanisms are at play, and the script checks both
 * because they cover different packages:
 *
 * - **Expo modules** (``expo-gl``, ``expo-notifications``, ...) are
 *   found by the autolinking *search* command, which scans
 *   ``node_modules`` for packages carrying an ``expo-module.config.json``.
 * - **Plain React Native modules** (``react-native-svg``,
 *   ``react-native-pager-view``) are found by the *react-native-config*
 *   command, which reads each package's native build files.
 *
 * Note that ``expo-build-properties`` is deliberately absent: it is a
 * config plugin that only adjusts Gradle settings at prebuild time, and
 * has no runtime native module of its own.
 *
 * This is the same resolution Gradle performs at build time, so a
 * module listed here is a module in the APK. A module missing here is
 * the reason for a `Can't find ViewManager 'RNXxx'` crash at runtime.
 *
 * The search results are matched by package name rather than by
 * parsing the whole payload: the command prints class instances
 * (``ExpoModuleConfig { ... }``) that are not valid JavaScript, so the
 * output is scanned as text instead.
 */

import { execFileSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/** Expo modules -- found by the `search` command. */
const EXPO_MODULES = [
  "expo-gl",
  "expo-notifications",
  "expo-device",
  "expo-sharing",
  "expo-blur",
  "expo-splash-screen",
  "expo-secure-store",
  "expo-dev-client",
];

/** Plain React Native modules -- found by the `react-native-config` command. */
const RN_MODULES = ["react-native-svg", "react-native-pager-view"];

const cli = join(
  projectRoot,
  "node_modules",
  "expo-modules-autolinking",
  "bin",
  "expo-modules-autolinking.js",
);

/**
 * Run the autolinking CLI and return its stdout.
 *
 * @param {string[]} args - CLI arguments.
 * @returns {string} The output, with ANSI colour codes stripped.
 */
function run(args) {
  const output = execFileSync("node", [cli, ...args], {
    cwd: projectRoot,
    encoding: "utf8",
  });
  // The command colours its output, and the colour codes are not valid
  // JavaScript -- strip them before scanning.
  // eslint-disable-next-line no-control-regex
  return output.replace(/\u001b\[[0-9;]*m/g, "");
}

// The search output lists each package under a `name: '...'` key. The
// package's own name is what matters, so the text is scanned for it.
const searched = run(["search", "--platform", "android"]);
const rnConfig = run(["react-native-config", "--platform", "android"]);

let linked = 0;
const missing = [];

console.log("expo modules:");
for (const name of EXPO_MODULES) {
  // `name: 'expo-gl',` -- the package's own name, not a path that
  // merely contains it.
  const found = new RegExp(`name: '${name}'`).test(searched);
  if (found) {
    linked += 1;
    console.log(`  ${name.padEnd(26)} linked`);
  } else {
    missing.push(name);
    console.log(`  ${name.padEnd(26)} MISSING`);
  }
}

console.log("react native modules:");
for (const name of RN_MODULES) {
  const found = new RegExp(`^\\s*'?${name}'?:`, "m").test(rnConfig);
  if (found) {
    linked += 1;
    console.log(`  ${name.padEnd(26)} linked`);
  } else {
    missing.push(name);
    console.log(`  ${name.padEnd(26)} MISSING`);
  }
}

const total = EXPO_MODULES.length + RN_MODULES.length;
console.log(`\n${linked}/${total} native modules linked.`);
if (missing.length > 0) {
  console.log(`missing: ${missing.join(", ")}`);
  process.exit(1);
}
