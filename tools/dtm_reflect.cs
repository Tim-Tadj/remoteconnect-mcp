using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;

internal static class DtmReflect
{
    private static readonly List<string> SearchDirectories = new List<string>();

    private static Assembly ResolveReflectionOnly(object sender, ResolveEventArgs args)
    {
        string file = new AssemblyName(args.Name).Name + ".dll";
        foreach (string directory in SearchDirectories)
        {
            string candidate = Path.Combine(directory, file);
            if (File.Exists(candidate))
                return Assembly.ReflectionOnlyLoadFrom(candidate);
        }
        try { return Assembly.ReflectionOnlyLoad(args.Name); }
        catch { }
        return null;
    }

    private static bool Mentions(Type type, string filter)
    {
        if (type == null) return false;
        return TypeName(type).IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0;
    }

    private static bool Matches(Type type, string filter)
    {
        if (Mentions(type, filter) || Mentions(type.BaseType, filter)) return true;
        try { if (type.GetInterfaces().Any(i => Mentions(i, filter))) return true; }
        catch { }
        BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
        try
        {
            foreach (PropertyInfo property in type.GetProperties(flags))
                if (Mentions(property.PropertyType, filter) || property.GetIndexParameters().Any(p => Mentions(p.ParameterType, filter))) return true;
            foreach (MethodInfo method in type.GetMethods(flags))
                if (Mentions(method.ReturnType, filter) || method.GetParameters().Any(p => Mentions(p.ParameterType, filter))) return true;
            foreach (ConstructorInfo ctor in type.GetConstructors(flags))
                if (ctor.GetParameters().Any(p => Mentions(p.ParameterType, filter))) return true;
        }
        catch { }
        return false;
    }

    private static string TypeName(Type type)
    {
        if (type == null) return "<null>";
        if (!type.IsGenericType) return type.FullName ?? type.Name;
        string name = type.GetGenericTypeDefinition().FullName;
        return name + "[" + String.Join(",", type.GetGenericArguments().Select(TypeName).ToArray()) + "]";
    }

    private static void PrintType(Type type)
    {
        Console.WriteLine("TYPE " + type.FullName);
        Console.WriteLine("  assembly=" + type.Assembly.FullName);
        Console.WriteLine("  base=" + TypeName(type.BaseType));
        foreach (Type iface in type.GetInterfaces()) Console.WriteLine("  interface=" + TypeName(iface));
        BindingFlags flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
        foreach (ConstructorInfo ctor in type.GetConstructors(flags))
            Console.WriteLine("  ctor(" + String.Join(", ", ctor.GetParameters().Select(p => TypeName(p.ParameterType) + " " + p.Name).ToArray()) + ")");
        foreach (PropertyInfo property in type.GetProperties(flags))
            Console.WriteLine("  property " + TypeName(property.PropertyType) + " " + property.Name +
                "[" + String.Join(", ", property.GetIndexParameters().Select(p => TypeName(p.ParameterType) + " " + p.Name).ToArray()) + "]");
        foreach (MethodInfo method in type.GetMethods(flags))
        {
            if (method.IsSpecialName) continue;
            Console.WriteLine("  method " + TypeName(method.ReturnType) + " " + method.Name + "(" +
                String.Join(", ", method.GetParameters().Select(p => TypeName(p.ParameterType) + " " + p.Name).ToArray()) + ")");
        }
    }

    public static int Main(string[] args)
    {
        if (args.Length < 2)
        {
            Console.Error.WriteLine("usage: dtm_reflect <assembly> <type-filter> [search-dir ...]");
            return 2;
        }
        string assemblyPath = Path.GetFullPath(args[0]);
        SearchDirectories.Add(Path.GetDirectoryName(assemblyPath));
        for (int i = 2; i < args.Length; i++) SearchDirectories.Add(Path.GetFullPath(args[i]));
        AppDomain.CurrentDomain.ReflectionOnlyAssemblyResolve += ResolveReflectionOnly;
        Assembly assembly = Assembly.ReflectionOnlyLoadFrom(assemblyPath);
        string filter = args[1];
        Type[] types;
        try { types = assembly.GetTypes(); }
        catch (ReflectionTypeLoadException exc)
        {
            types = exc.Types.Where(t => t != null).ToArray();
            foreach (Exception loader in exc.LoaderExceptions) Console.Error.WriteLine("LOADER " + loader.Message);
        }
        foreach (Type type in types.Where(t => Matches(t, filter)))
            PrintType(type);
        return 0;
    }
}
