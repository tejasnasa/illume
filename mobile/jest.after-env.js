// Runs after the React Native environment is installed, which is why it is
// not part of ``jest.setup.js``: the testing library pulls in
// ``react-native/index.js``, which reads the ``__DEV__`` global that only
// exists once the preset's own setup has run.
//
// Under a full parallel run the render-heavy screens contend for CPU, and
// the default one-second ``waitFor`` window is short enough that a correct
// but loaded render times out. The assertions stay bounded; the window is
// just realistic for a machine running every suite at once.
const { configure } = require("@testing-library/react-native");

configure({ asyncUtilTimeout: 5000 });
jest.setTimeout(20000);
