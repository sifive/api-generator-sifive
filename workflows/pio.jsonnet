local bt = import 'build-target.libsonnet';

local scalaVersion = {
  major: 12,
  minor: 8
};

local Block(configs, scalaModules) = {
};

local loopbackScalaModule = {
  name: 'loopback',
  scalaVersion: scalaVersion,
  rootDir: bt.SourceString('block-pio-sifive', 'craft/loopback'),  // how to handle these paths?
  sourceDirs: [],
  resourceDirs: [],
  dependencies: ['sifiveSkeleton'],
  scalacOptions: ['-Xsource:2.11'],
};

local pioScalaModule = {
  name: 'pio',
  scalaVersion: scalaVersion,
  rootDir: bt.SourceString('block-pio-sifive', 'craft/pio'),  // how to handle these paths?
  sourceDirs: ['src'],
  resourceDirs: [],
  dependencies: [
    loopbackScalaModule,
    'sifiveSkeleton',
    'sifiveBlocks'
  ],
  scalacOptions: ['-Xsource:2.11'],
};


local testSocket = import 'test-socket.libsonnet';

local testHarness = testSocket.TestHarness(
  designName="testSocket",
  extraConfigs=['sifive.blocks.pio.WithpioTop'],
  extraScalaModules=[pioScalaModule]
);

local buildDirs = testHarness.buildDirs + {
  bsp:: self.root + '/bsp',
  metalInstall:: self.bsp + '/metal',
};

local buildFiles = testHarness.buildFiles + {
  dtb: buildDirs.bsp + '/' + testHarness.name + '.dtb',
  header: buildDirs.bsp + '/' + testHarness.name + '.h',
  inlineHeader: buildDirs.bsp + '/' + testHarness.name + '-inline.h',
  platformHeader: buildDirs.bsp + '/' + testHarness.name + '-platform.h',
  overlay: buildDirs.bsp + '/' + testHarness.name + '.overlay.dts',
  ldscript: buildDirs.bsp + '/' + testHarness.name + '.ld',
  attributes: buildDirs.bsp + '/' + testHarness.name + '.mk',
};

local testHarnessType = 'rtl';
local testHarnessLdscriptLayout = 'default';
local riscvHost = 'riscv64-unknown-elf';

local customOverlay = bt.Target(
  name='write',
  params={
    contents: |||
      /include/ "../firrtl/testSocket.dts"
      / {
        chosen {
          metal,entry = <&{/soc/mem@80000000} 0 0>;
          metal,ram = <&{/soc/mem@80000000} 0 0>;
        };
      };
    |||,
    path: buildFiles.overlay
  }
);

local BSP(customOverlay=null) = {
  local dutDTS = bt.targetField('dts', testHarness.rocketChip),
  local designDTS = if customOverlay == null then bt.Target(
    name='devicetree-overlay-generator',
    params={
      topDTSFile: dutDTS,
      type: testHarnessType,
      outputFile: buildFiles.overlay,
    }
  ) else customOverlay,

  local designDTB = bt.Target(
    name='dtc',
    params={
      inputFile: designDTS,
      inputFormat: 'dts',
      otherInputs: [dutDTS],
      outputFile: buildFiles.dtb,
      outputFormat: 'dtb'
    }
  ),

  headers:: bt.Target(
    name="freedom-header-generator",
    params={
      dtbFile: designDTB,
      metalHeaderFile: buildFiles.header,
      bareHeaderFile: buildFiles.platformHeader,
    }
  ),
  local headers = self.headers,

  linkerScript:: bt.Target(
    name="ldscript-generator",
    params={
      topDTSFile: designDTS,
      otherDTSFiles: [dutDTS],
      layout: testHarnessLdscriptLayout,
      outputFile: buildFiles.ldscript
    }
  ),
  local linkerScript = self.linkerScript,

  attributes:: bt.Target(
    name="esdk-settings-generator",
    params={
      topDTSFile: designDTS,
      otherDTSFiles: [dutDTS],
      type: testHarnessType,
      outputFile: buildFiles.attributes
    }
  ),
  local attributes = self.attributes,

  metal:: bt.Target(
    name="freedom-metal",
    outputDir=buildDirs.metalInstall,
    params={
      ARCH: bt.targetField('arch', attributes),
      ABI: bt.targetField('abi', attributes),
      CMODEL: bt.targetField('cmodel', attributes),
      host: riscvHost,
      machineHeader: bt.targetField('header', headers),
      machineInlineHeader: bt.targetField('inlineHeader', headers),
      platformHeader: bt.targetField('platformHeader', headers),
      machineLdScript: linkerScript,
      resources: ['riscv-tools/2019.08.0'],
    }
  ),
};

[
  BSP(customOverlay).headers,
  BSP(customOverlay).linkerScript,
  BSP(customOverlay).attributes,
  BSP(customOverlay).metal,
]
