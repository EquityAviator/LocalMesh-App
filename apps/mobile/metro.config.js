const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);

// The generated protocol types live in the workspace package.
config.resolver.extraNodeModules = {
  '@localmesh/mesh-protocol': require('path').resolve(__dirname, '../../packages/mesh-protocol'),
};
config.watchFolders = [require('path').resolve(__dirname, '../../packages/mesh-protocol')];

module.exports = config;
