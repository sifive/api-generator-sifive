{
  Target(name, params, outputDir=null): {
    '$target': name,
    params: params,
    [if outputDir != null then 'outputDir']: outputDir,
  },

  targetField(field, target): [{ '$field': field }, target],

  Job(cmdline, inputs): self.Target(
    name='job',
    params={
      command: cmdline,
      visible: inputs,
    }
  ),

  SourceString(root, file=null): self.Target(
    name='sources',
    params={
      string: root,
      [if file != null then 'file']: file
    }
  ),
  SourcePath(root, file): self.Target(
    name='sources',
    params={
      fileIn: root,
      path: file
    }
  ),
  SourcePaths(root, directory, regex): self.Target(
    name='sources',
    params={
      filesIn: root,
      directory: directory,
      regex: regex
    }
  )
}
