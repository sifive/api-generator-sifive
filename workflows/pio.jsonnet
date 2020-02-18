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
  bsp: self.root + '/bsp',
};

local buildFiles = testHarness.buildFiles + {
  dtb: buildDirs.bsp + '/' + testHarness.name + '.dtb',
  header: buildDirs.bsp + '/' + testHarness.name + '.h',
  inlineHeader: buildDirs.bsp + '/' + testHarness.name + '-inline.h',
  platformHeader: buildDirs.bsp + '/' + testHarness.name + '-platform.h',
  overlay: buildDirs.bsp + '/' + testHarness.name + '.overlay.dts',
};

local testHarnessType = 'rtl';

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
  local overlay = if customOverlay == null then bt.Target(
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
      inputFile: overlay,
      inputFormat: 'dts',
      otherInputs: [dutDTS],
      outputFile: buildFiles.dtb,
      outputFormat: 'dtb'
    }
  ),

  header:: bt.Target(
    name="freedom-header-generator",
    params={
      dtbFile: designDTB,
      metalHeaderFile: buildFiles.header,
      bareHeaderFile: buildFiles.platformHeader,
    }
  )

};

BSP(customOverlay).header
