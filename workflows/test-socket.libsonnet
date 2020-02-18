local bt = import 'build-target.libsonnet';

{
  TestHarness(designName, extraConfigs=[], extraScalaModules=[]):: {
    name:: designName,
    buildDirs:: {
      root: 'build/' + designName,
      firrtl: self.root + '/firrtl',
      verilog: self.root + '/verilog',
      metadata: self.root + '/metadata',
    },
    local buildDirs = self.buildDirs,

    buildFiles:: {
      blackboxList: buildDirs.metadata + '/blackboxes.txt',
      memsConf: buildDirs.firrtl + '/mems.conf',
      ramsV: buildDirs.verilog + '/' + designName + '.behav_srams.v',
      romsV: buildDirs.verilog + '/' + designName + '.roms.v',
    },
    local buildFiles = self.buildFiles,

    local scalaModuleDeps = ['sifiveSkeleton', 'listBlackBoxes'] + extraScalaModules,
    local scalaVersion = { major: 12, minor: 8 },
    local scalaModuleName = designName + 'ScalaModule',
    local scalaModule = bt.Target(
      name='scala-module',
      params={
        name: scalaModuleName,
        scalaVersion: scalaVersion,
        rootDir: buildDirs.root,
        dependencies: scalaModuleDeps,
        sourceDirs: [],
        resourceDirs: [],
      },
    ),

    local classpath = bt.targetField('classpath', scalaModule),
    local topName = 'SkeletonTestHarness',

    rocketChip:: bt.Target(
      name='rocket-chip',
      outputDir=buildDirs.firrtl,
      params={
        classpath: classpath,
        topModule: 'sifive.skeleton.SkeletonTestHarness',
        configs: ['sifive.skeleton.DefaultConfig'] + extraConfigs,
        baseFilename: designName,
      },
    ),
    local rocketChip = self.rocketChip,

    firrtl:: bt.Target(
      name='firrtl',
      outputDir=buildDirs.verilog,
      params={
        classpath: classpath,
        topname: topName,
        inputFile: bt.targetField('firrtlFile', rocketChip),
        annotations: [
          bt.targetField('firrtlAnnoFile', rocketChip),
          {
            filename: 'cmdline.anno.json',
            jvalue: [
              {
                class: 'sifive.freedom.firrtl.BlackBoxListAnnotation',
                filename: buildFiles.blackboxList,
              },
            ],
          },
        ],
        inferRW: true,
        replSeqMem: [{ circuit: topName, confFile: 'mems.conf' }],
        splitModules: true,
        infoMode: 'ignore',
        customTransforms: [
          'sifive.freedom.firrtl.ListBlackBoxesTransform',
        ],
        javaOptions: ['-Xmx15G', '-Xss5M'],
        compiler: 'sverilog',
        visibleFiles: bt.Target(
          name='mkdir',
          params=[
            buildDirs.verilog,
            buildDirs.metadata,
          ],
        ),
      },
    ),
  },
}
