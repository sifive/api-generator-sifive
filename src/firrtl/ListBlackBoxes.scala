// See LICENSE for license details.

package sifive.freedom.firrtl

import java.io.{File, FileWriter}

import firrtl._
import firrtl.annotations._
import firrtl.ir._
import firrtl.transforms.{BlackBoxInlineAnno, BlackBoxResourceAnno}

case class BlackBoxListAnnotation(filename: String) extends NoTargetAnnotation

class ListBlackBoxesTransform extends Transform {
  def inputForm: CircuitForm = HighForm
  def outputForm: CircuitForm = HighForm

  private def writeFile(filename: String, modules: Seq[String]) {
    val writer = new FileWriter(new File(filename))
    writer.write(modules.mkString("\n"))
    writer.close()
  }

  def execute(state: CircuitState): CircuitState = {
    val file: Option[String] = state.annotations.collectFirst {
      case BlackBoxListAnnotation(fn) => fn
    }

    if (file.isDefined) {
      val circuit = state.circuit

      // Exclude black boxes that are dynamically generated or already
      // aggregated with the emitted RTL
      val omitMods = state.annotations.collect {
        case BlackBoxResourceAnno(m, _) => Seq(m.name)
        case BlackBoxInlineAnno(m, _, _) => Seq(m.name)
      }.flatten.toSet

      val extMods = circuit.modules.collect {
        case ext: ExtModule if (!omitMods.contains(ext.name)) => ext.defname
      }.distinct.sorted

      file.foreach { writeFile(_, extMods) }
    }

    state
  }
}
