import ghidra.GhidraApplicationLayout;
import ghidra.GhidraLaunchable;
import ghidra.framework.Application;
import ghidra.framework.HeadlessGhidraApplicationConfiguration;
import ghidra.base.project.GhidraProject;
import ghidra.program.flatapi.FlatProgramAPI;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.app.decompiler.*;
import ghidra.util.task.TaskMonitor;
import java.io.*;

public class RecoverViewMain implements GhidraLaunchable {
 public void launch(GhidraApplicationLayout layout,String[] args) throws Exception {
  Application.initializeApplication(layout,new HeadlessGhidraApplicationConfiguration());
  GhidraProject project=GhidraProject.openProject(args[0],args[1],true);
  Program program=project.openProgram("/",args[2],false);
  int tx=program.startTransaction("Recover camera functions");
  FlatProgramAPI api=new FlatProgramAPI(program,TaskMonitor.DUMMY);
  DecompInterface d=new DecompInterface();d.openProgram(program);
  try(PrintWriter out=new PrintWriter(new File(args[3]),"UTF-8")){
   for(int i=4;i<args.length;i++){
    Address a=program.getImageBase().add(Long.parseLong(args[i],16));
    Function containing=program.getFunctionManager().getFunctionContaining(a);
    if(containing!=null&&!containing.getEntryPoint().equals(a))program.getFunctionManager().removeFunction(containing.getEntryPoint());
    api.disassemble(a);
    Function f=api.getFunctionAt(a);if(f==null)f=api.createFunction(a,"recovered_"+args[i]);
    out.println("\n/* ENTRY "+args[i]+" */");
    if(f==null){out.println("NO FUNCTION");continue;}
    DecompileResults r=d.decompileFunction(f,60,TaskMonitor.DUMMY);
    out.println(r.decompileCompleted()?r.getDecompiledFunction().getC():r.getErrorMessage());out.flush();
   }
  } finally {d.dispose();program.endTransaction(tx,true);project.save(program);project.close();}
 }
}
