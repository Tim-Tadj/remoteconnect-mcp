using System;
using System.Collections;
using System.IO;
using System.Reflection;

internal static class DtmHeadlessProbe
{
    private static string Install = @"C:\Program Files (x86)\Schneider Electric\RemoteConnect";
    private static string Module = Path.Combine(Install, @"Modules\FdtDtmContainerSample");

    private static Assembly Resolve(object sender, ResolveEventArgs args)
    {
        string name = new AssemblyName(args.Name).Name + ".dll";
        foreach (string dir in new[] { Module, Install, Path.Combine(Install, "CBS", "FDTDTM") })
        {
            string path = Path.Combine(dir, name);
            if (File.Exists(path)) return Assembly.LoadFrom(path);
        }
        return null;
    }

    private static object Get(object target, string property)
    {
        return target.GetType().GetProperty(property).GetValue(target, null);
    }

    public static int Main(string[] args)
    {
        if (args.Length != 1 || !File.Exists(args[0]))
        {
            Console.Error.WriteLine("usage: dtm_headless_probe <project.prj>");
            return 2;
        }
        AppDomain.CurrentDomain.AssemblyResolve += Resolve;
        Environment.CurrentDirectory = Install;
        try
        {
            Assembly serviceAssembly = Assembly.LoadFrom(Path.Combine(Module, "FdtDtm.Sample.ProjectService.dll"));
            Type serviceType = serviceAssembly.GetType("FdtDtm.Sample.ProjectService.ProjectService", true);
            object service = Activator.CreateInstance(serviceType, true);
            string path = Path.GetFullPath(args[0]);
            string name = Path.GetFileNameWithoutExtension(path);
            serviceType.GetMethod("Open", new[] { typeof(string), typeof(string) }).Invoke(service, new object[] { name, path });
            object project = Get(service, "FrameProject");
            object dtms = Get(project, "DTMs");
            int count = (int)dtms.GetType().GetMethod("Count").Invoke(dtms, null);
            Console.WriteLine("opened=" + path);
            Console.WriteLine("dtm_count=" + count);
            foreach (object item in (IEnumerable)dtms)
                Console.WriteLine("dtm=" + Get(item, "DTMID") + "\t" + Get(item, "TAG"));
            serviceType.GetMethod("Close").Invoke(service, null);
            return 0;
        }
        catch (Exception exc)
        {
            while (exc is TargetInvocationException && exc.InnerException != null) exc = exc.InnerException;
            Console.Error.WriteLine(exc);
            return 1;
        }
    }
}
