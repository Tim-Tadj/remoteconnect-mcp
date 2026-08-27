using System;
using System.Collections.Specialized;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using FdtDtm.Sample.ProjectFileAdapter;
using FdtDtm.Sample.ProjectService;
using FdtDtm.Sample.ProjectService.Interface;
using Fdt.Dtm.Functions;
using OEMFDTContainer.Runtime;
using TSF.CBS.FdtDtm.FdtContainerService;
using TSF.ToolPattern.Hosting;
using Callbacks = OEMFDTContainer.Runtime.Callbacks;

internal sealed class HeadlessEnvironment : IEnvironment
{
    private readonly string temporaryFilesPath;

    public HeadlessEnvironment(string installPath)
    {
        BaseDirectory = installPath;
        CommonApplicationDataPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
            "Schneider Electric", "RemoteConnect");
        UserSettingsPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Schneider Electric", "RemoteConnect");
        temporaryFilesPath = Path.Combine(Path.GetTempPath(), "remoteconnect-mcp");
        Directory.CreateDirectory(temporaryFilesPath);
    }

    public string ApplicationName { get { return "RemoteConnect MCP"; } }
    public string ApplicationVersion { get { return "0.16.2"; } }
    public string ApplicationManufacturer { get { return "Schneider Electric"; } }
    public string BaseDirectory { get; private set; }
    public string CommonApplicationDataPath { get; private set; }
    public string UserSettingsPath { get; private set; }
    public string TemporaryFilesPath { get { return temporaryFilesPath; } }
    public NameValueCollection InstallParams { get { return new NameValueCollection(); } }

    public string GenerateTemporaryFolder()
    {
        string path = Path.Combine(temporaryFilesPath, Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path;
    }
}

internal sealed class HeadlessProjectSelector : IProjectSelector
{
    public string SelectNewProject() { throw new NotSupportedException("An explicit output path is required."); }
    public string SelectExistingProject() { throw new NotSupportedException("An explicit input path is required."); }
    public string NewProjectName() { throw new NotSupportedException("An explicit project name is required."); }
}

internal sealed class CompositeDtmEnvironment : Callbacks.IEnvironment
{
    private readonly Callbacks.IDBAdapter2 database;
    private readonly Callbacks.IEnvironment services;

    public CompositeDtmEnvironment(Callbacks.IDBAdapter2 database, Callbacks.IEnvironment services)
    {
        this.database = database;
        this.services = services;
    }

    public Callbacks.IDBAdapter2 Database { get { return database; } }
    public Callbacks.IEnvironmentGui EnvironmentGui { get { return services.EnvironmentGui; } }
    public Callbacks.IEnvironmentCommChannels EnvironmentCommChannels { get { return services.EnvironmentCommChannels; } }
    public Callbacks.IMultiUserEnvironment MultiUserEnvironment { get { return services.MultiUserEnvironment; } }
    public Callbacks.IDTMCallbackInterceptor CallbackInterceptor { get { return services.CallbackInterceptor; } }
    public Callbacks.IClrExtensionManager ClrExtensionManager { get { return services.ClrExtensionManager; } }
    public Callbacks.ICustomBusAddressProvider CustomBusAddressProvider { get { return services.CustomBusAddressProvider; } }
}

internal static class RemoteConnectBridge
{
    private static readonly string Install = Environment.GetEnvironmentVariable("REMOTECONNECT_HOME") ??
        @"C:\Program Files (x86)\Schneider Electric\RemoteConnect";
    private static readonly string Module = Path.Combine(Install, @"Modules\FdtDtmContainerSample");
    private static readonly string X70Dtm =
        @"C:\Program Files (x86)\Common Files\FDT\DTMs\Schneider Electric\SCADAPack x70";

    private static Assembly Resolve(object sender, ResolveEventArgs args)
    {
        string name = new AssemblyName(args.Name).Name + ".dll";
        foreach (string dir in new[] { Module, Install, Path.Combine(Install, "CBS", "FDTDTM"), X70Dtm })
        {
            string path = Path.Combine(dir, name);
            if (File.Exists(path)) return Assembly.LoadFrom(path);
        }
        return null;
    }

    private static void DumpFunctions(System.Collections.Generic.IEnumerable<FunctionItem> items, string prefix)
    {
        foreach (FunctionItem function in items)
        {
            FunctionGroup group = function as FunctionGroup;
            if (group != null)
            {
                DumpFunctions(group.FunctionItems, prefix + group.Label + "/");
                continue;
            }
            ExecutableFunction executable = function as ExecutableFunction;
            if (executable == null) continue;
            Console.WriteLine("function=" + executable.FunctionId + "\t" +
                function.GetType().Name + "\t" + prefix + function.Label +
                "\tenabled=" + function.Enabled + "\thidden=" + function.Hidden);
            CommandFunction command = function as CommandFunction;
            if (command == null || command.InputArguments == null) continue;
            foreach (FunctionArgumentDescription argument in command.InputArguments)
                Console.WriteLine("argument=" + executable.FunctionId + "\t" + argument.Id +
                    "\t" + argument.Label + "\t" + argument.DataType +
                    "\toptional=" + argument.IsOptional + "\tdefault=" + argument.DefaultValue);
        }
    }

    private static PropertyInfo FindProperty(Type type, string name)
    {
        while (type != null)
        {
            PropertyInfo property = type.GetProperty(
                name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (property != null) return property;
            type = type.BaseType;
        }
        throw new MissingMemberException(name);
    }

    private static object Construct(Type type, params object[] arguments)
    {
        return Activator.CreateInstance(
            type, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
            null, arguments, CultureInfo.InvariantCulture);
    }

    private static object GetDeviceModel(IFDT2DTMProxy proxy)
    {
        object providerInteractor = proxy.FDTDTM.CommandFunction;
        Console.WriteLine("fdt_dtm_runtime_type=" + proxy.FDTDTM.GetType().AssemblyQualifiedName);
        Console.WriteLine("command_provider_runtime_type=" + providerInteractor.GetType().AssemblyQualifiedName);
        object signalAdapter = FindProperty(providerInteractor.GetType(), "WrappedObject")
            .GetValue(providerInteractor, null);
        object roleContainer = FindProperty(signalAdapter.GetType(), "DeviceRoleContainer")
            .GetValue(signalAdapter, null);
        object roleAccess = FindProperty(roleContainer.GetType(), "DeviceModelRoleAccess")
            .GetValue(roleContainer, null);
        object provider = FindProperty(roleAccess.GetType(), "CommandFunction")
            .GetValue(roleAccess, null);
        Console.WriteLine("unwrapped_provider_type=" + provider.GetType().AssemblyQualifiedName);
        return FindProperty(provider.GetType(), "DeviceModel").GetValue(provider, null);
    }

    private static object CreateExcelConfig(object deviceModel, out Type excelType)
    {
        Assembly dtmAssembly = deviceModel.GetType().Assembly;
        excelType = dtmAssembly.GetType(
            "Schneider_Electric.SCADAPackRTUDeviceDtm.Dtm.ThirdParty.ExcelConfigFile", true);
        return Construct(excelType, deviceModel, CultureInfo.GetCultureInfo("en-US"));
    }

    private static void ExportWorkbook(IFDT2DTMProxy proxy, string outputPath)
    {
        object deviceModel = GetDeviceModel(proxy);
        Assembly dtmAssembly = deviceModel.GetType().Assembly;
        Type excelType;
        object excel = CreateExcelConfig(deviceModel, out excelType);
        Type configType = dtmAssembly.GetType(
            "Schneider_Electric.SCADAPackRTUDeviceDtm.Dtm.ConfigFile.ConfigParameters", true);
        object offlineDataset = FindProperty(deviceModel.GetType(), "OfflineDataset")
            .GetValue(deviceModel, null);
        object parameterAccess = FindProperty(offlineDataset.GetType(), "ParameterAccess")
            .GetValue(offlineDataset, null);
        object config = Construct(configType, parameterAccess, deviceModel);
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath));
        using (FileStream stream = new FileStream(outputPath, FileMode.Create, FileAccess.Write, FileShare.None))
        {
            object[] invokeArguments = { stream, config, null, "Exporting configuration...", false, false };
            excelType.GetMethod(
                "CreateFromParameterSet", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                .Invoke(excel, invokeArguments);
            Console.WriteLine("export_canceled=" + invokeArguments[4]);
            Console.WriteLine("export_complex_objects=" + invokeArguments[5]);
        }
        Console.WriteLine("exported=" + outputPath + "\tbytes=" + new FileInfo(outputPath).Length);
    }

    private static void ImportWorkbook(IFDT2DTMProxy proxy, string inputPath)
    {
        object deviceModel = GetDeviceModel(proxy);
        Type excelType;
        object excel = CreateExcelConfig(deviceModel, out excelType);
        string logPath = Path.ChangeExtension(inputPath, ".import.log.txt");
        bool imported;
        object[] invokeArguments;
        using (FileStream input = new FileStream(inputPath, FileMode.Open, FileAccess.Read, FileShare.Read))
        using (FileStream log = new FileStream(logPath, FileMode.Create, FileAccess.Write, FileShare.Read))
        {
            invokeArguments = new object[] { input, log, null, "Importing configuration...", false };
            imported = (bool)excelType.GetMethod(
                "Parse", BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                .Invoke(excel, invokeArguments);
        }
        proxy.Save();
        Console.WriteLine("imported=" + imported + "\tcanceled=" + invokeArguments[4] +
            "\tworkbook=" + inputPath + "\tlog=" + logPath +
            "\tlog_bytes=" + new FileInfo(logPath).Length);
        if (!imported) throw new InvalidDataException("The x70 DTM rejected the workbook. See " + logPath);
    }

    public static int Main(string[] args)
    {
        bool creating = args.Length == 3 && args[1] == "--create";
        if ((args.Length != 1 && args.Length != 3) ||
            (!creating && !File.Exists(args[0])) ||
            (creating && File.Exists(args[0])))
        {
            Console.Error.WriteLine("usage: RemoteConnectBridge <project.prj> [--export output.xls | --import input.xls | --create controller]");
            return 2;
        }
        AppDomain.CurrentDomain.AssemblyResolve += Resolve;
        Environment.CurrentDirectory = Install;
        int result = Run(args[0], args.Length == 3 ? args[1] : null,
            args.Length == 3 ? args[2] : null);
        Environment.Exit(result);
        return result;
    }

    [MethodImpl(MethodImplOptions.NoInlining)]
    private static int Run(string inputPath, string operation, string workbookPath)
    {
        try
        {
            string projectPath = Path.GetFullPath(inputPath);
            string projectName = Path.GetFileNameWithoutExtension(projectPath);
            HeadlessEnvironment hostEnvironment = new HeadlessEnvironment(Install);

            FileAdapter2 fileAdapter = new FileAdapter2(new HeadlessProjectSelector());
            typeof(FileAdapter2).GetProperty("Environment").SetValue(fileAdapter, hostEnvironment, null);
            fileAdapter.Initialize();
            if (operation != "--create") fileAdapter.PrepareProjectItem(projectName, projectPath);

            LogEventListener log = new LogEventListener();
            TSF.CBS.FdtDtm.FdtContainerService.CatalogDBAdapter.CatalogDBAdapter catalog =
                new TSF.CBS.FdtDtm.FdtContainerService.CatalogDBAdapter.CatalogDBAdapter(hostEnvironment);
            string catalogPath = Path.Combine(
                hostEnvironment.CommonApplicationDataPath, "DTMCatalog", "DTMCatalog.xml");
            if (!catalog.SetCatalogFullPath(catalogPath))
                throw new InvalidOperationException("Could not select DTM catalog: " + catalogPath);

            ExternalDependency external = new ExternalDependency();
            string assemblyLocation = external.GetAssemblyLocation();
            string serviceDirectory = external.GetDirectoryName(assemblyLocation);
            string installedConfig = Path.Combine(Install, @"CBS\FDTDTM\RuntimeFrame.dll.config");
            string runtimeConfig = "remoteconnect-mcp.RuntimeFrame.config";
            string localConfig = Path.Combine(serviceDirectory, runtimeConfig);
            string configText = File.ReadAllText(installedConfig).Replace(
                @".\CBS\FDTDTM\FDT XML Schemas",
                Path.Combine(Install, @"CBS\FDTDTM\FDT XML Schemas"));
            File.WriteAllText(localConfig, configText);
            string resolvedConfig = serviceDirectory + @"\" + runtimeConfig;
            Console.Error.WriteLine("assembly_location=" + assemblyLocation);
            Console.Error.WriteLine("runtime_config=" + resolvedConfig + " exists=" + external.FileExists(resolvedConfig));
            using (FdtContainerService container = new FdtContainerService(catalog, log, runtimeConfig, external))
            {
                typeof(FdtContainerService).GetMethod(
                    "Initialize", BindingFlags.Instance | BindingFlags.NonPublic).Invoke(container, null);
                CompositeDtmEnvironment projectEnvironment =
                    new CompositeDtmEnvironment(fileAdapter, container);
                IDTMCatalog dtmCatalog = container.FdtContainer.GetDTMCatalog(
                    DataAccessModeEnum.read, log);
                Console.WriteLine("catalog_device_types=" +
                    dtmCatalog.DeviceTypeQuery("", "").Length);
                UserInformation[] competing;
                IFrameProject project;
                if (operation == "--create")
                {
                    project = container.FdtContainer.CreateProject(projectName, projectEnvironment, log);
                    DTMCatalogData.DeviceTypeInfoEntry commEntry = null;
                    DTMCatalogData.DeviceTypeInfoEntry controllerEntry = null;
                    foreach (DTMCatalogData.DeviceTypeInfoEntry entry in dtmCatalog.DeviceTypeQuery("", ""))
                    {
                        if (entry.Name == "SCADAPack CommDTM") commEntry = entry;
                        if (entry.Name == "SCADAPack x70") controllerEntry = entry;
                    }
                    if (commEntry == null || controllerEntry == null)
                        throw new InvalidOperationException("The installed catalog does not contain the SCADAPack CommDTM and x70 DTM.");
                    IDTMListItem commItem = project.DTMs.AddDtm(TypeInfoProvider.Create(commEntry));
                    project.Topology.AddDTM(commItem.DTMID, "", "", false);
                    string channelId = null;
                    using (IDTMProxy commProxy = commItem.OpenDTM())
                    {
                        foreach (CommChannelInfo channel in commProxy.CommChannelInfos)
                        {
                            Console.WriteLine("comm_channel=" + channel.Id + "\t" + channel.Label);
                            if (channelId == null) channelId = channel.Id;
                        }
                    }
                    if (channelId == null)
                        throw new InvalidOperationException("The SCADAPack CommDTM exposed no communication channel.");
                    IDTMListItem controllerItem = project.DTMs.AddDtm(TypeInfoProvider.Create(controllerEntry));
                    project.Topology.AddDTM(controllerItem.DTMID, commItem.DTMID, channelId, true);
                    using (IDTMProxy controllerProxy = controllerItem.OpenDTM())
                    {
                        controllerProxy.Save();
                    }
                    Console.WriteLine("created=" + projectPath + "\tcontroller=" + workbookPath);
                }
                else
                {
                    project = container.FdtContainer.OpenProject(
                        projectName, projectEnvironment, DataAccessModeEnum.exclusive,
                        out competing, log);
                    Console.WriteLine("opened=" + projectPath);
                }
                Console.WriteLine("dtm_count=" + project.DTMs.Count());
                foreach (IDTMListItem item in project.DTMs)
                {
                    Fdt2TypeInfoProvider fdt2 = item.DTMTypeInfo as Fdt2TypeInfoProvider;
                    Console.WriteLine("dtm=" + item.DTMID + "\t" + item.TAG +
                        "\tinstalled=" + item.IsInstalled +
                        (fdt2 == null ? "" : "\troot=" + fdt2.DtmRootPath));
                }
                foreach (IDTMListItem item in project.DTMs)
                {
                    if (!String.Equals(item.DTMTypeInfo.Name, "SCADAPack x70", StringComparison.OrdinalIgnoreCase)) continue;
                    using (IDTMProxy proxy = item.OpenDTM())
                    {
                        if (String.IsNullOrEmpty(operation))
                            DumpFunctions(proxy.DTMFunctions.FunctionItems, "");
                        else if (operation == "--export")
                            ExportWorkbook((IFDT2DTMProxy)proxy, Path.GetFullPath(workbookPath));
                        else if (operation == "--import")
                            ImportWorkbook((IFDT2DTMProxy)proxy, Path.GetFullPath(workbookPath));
                        else if (operation != "--create")
                            throw new ArgumentException("Unknown operation: " + operation);
                    }
                }
                project.SaveProject(true);
                fileAdapter.Save(projectName, projectPath, operation == "--create");
                project.DisposeRequest(false);
                fileAdapter.Close(projectName);

                fileAdapter.PrepareProjectItem(projectName, projectPath);
                CompositeDtmEnvironment verifyEnvironment =
                    new CompositeDtmEnvironment(fileAdapter, container);
                IFrameProject verified = container.FdtContainer.OpenProject(
                    projectName, verifyEnvironment, DataAccessModeEnum.exclusive,
                    out competing, log);
                Console.WriteLine("reopened_dtm_count=" + verified.DTMs.Count());
                verified.DisposeRequest(false);
                dtmCatalog.Dispose();
            }
            fileAdapter.Close(projectName);
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
