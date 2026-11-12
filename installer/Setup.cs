// GluePaw 安装程序
// C# / WinForms，.NET Framework 4
// payload.zip 以嵌入资源方式打进本程序，安装时直接解压到安装目录，
// 全程不依赖 %TEMP%，解决某些机器上临时目录不可写导致安装失败的问题。
// 编译（示例）：
//   csc /nologo /target:winexe /optimize+ /out:Setup.exe /win32icon:GluePaw.ico
//       /resource:payload.zip /r:Microsoft.CSharp.dll Setup.cs
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Windows.Forms;
using Microsoft.Win32;

namespace GluePawSetup
{
    internal static class Core
    {
        public const string AppName = "GluePaw";
        public const string AppVersion = "1.0.0";
        public const string Publisher = "hengjunguo35-oss";
        public const string ExeName = "GluePaw.exe";

        public static string DefaultDir
        {
            get
            {
                string baseDir = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                return Path.Combine(baseDir, "Programs", AppName);
            }
        }

        public static bool Install(string dir, bool desktopIcon, Action<string> report)
        {
            try
            {
                report("正在创建安装目录…");
                Directory.CreateDirectory(dir);

                report("正在解压程序文件…");
                using (Stream s = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
                {
                    if (s == null) throw new Exception("安装包数据缺失");
                    using (ZipArchive zip = new ZipArchive(s, ZipArchiveMode.Read))
                    {
                        foreach (ZipArchiveEntry e in zip.Entries)
                        {
                            string target = Path.Combine(dir, e.FullName.Replace('/', Path.DirectorySeparatorChar));
                            if (string.IsNullOrEmpty(e.Name))
                            {
                                Directory.CreateDirectory(target);
                                continue;
                            }
                            string parent = Path.GetDirectoryName(target);
                            if (!string.IsNullOrEmpty(parent)) Directory.CreateDirectory(parent);
                            using (Stream es = e.Open())
                            using (FileStream fs = new FileStream(target, FileMode.Create, FileAccess.Write))
                            {
                                es.CopyTo(fs);
                            }
                        }
                    }
                }

                string exe = Path.Combine(dir, ExeName);
                if (!File.Exists(exe)) throw new Exception("未找到 " + ExeName);

                report("正在创建快捷方式…");
                CreateShortcut(
                    Path.Combine(
                        Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),
                        "Programs", AppName, AppName + ".lnk"),
                    exe, dir);
                if (desktopIcon)
                {
                    CreateShortcut(
                        Path.Combine(
                            Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
                            AppName + ".lnk"),
                        exe, dir);
                }

                report("正在写入卸载信息…");
                WriteUninstaller(dir, exe);
                RegisterUninstall(dir, exe);

                report("安装完成");
                return true;
            }
            catch (Exception ex)
            {
                try { report("错误：" + ex.Message); } catch { }
                return false;
            }
        }

        private static void CreateShortcut(string lnkPath, string exe, string dir)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(lnkPath));
                Type t = Type.GetTypeFromProgID("WScript.Shell");
                dynamic shell = Activator.CreateInstance(t);
                dynamic sc = shell.CreateShortcut(lnkPath);
                sc.TargetPath = exe;
                sc.WorkingDirectory = dir;
                sc.Description = "GluePaw 剪贴板历史管理器";
                sc.Save();
            }
            catch
            {
                // 快捷方式创建失败不阻塞安装
            }
        }

        private static void WriteUninstaller(string dir, string exe)
        {
            string bat = Path.Combine(dir, "uninstall.bat");
            string lnk1 = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.StartMenu),
                "Programs", AppName, AppName + ".lnk");
            string lnk2 = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),
                AppName + ".lnk");
            string content =
                "@echo off\r\n" +
                "taskkill /IM " + ExeName + " /F >nul 2>&1\r\n" +
                "reg delete \"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + AppName + "\" /f >nul 2>&1\r\n" +
                "del /q \"" + lnk1 + "\" >nul 2>&1\r\n" +
                "rmdir \"" + Path.GetDirectoryName(lnk1) + "\" >nul 2>&1\r\n" +
                "del /q \"" + lnk2 + "\" >nul 2>&1\r\n" +
                "cd /d \"%USERPROFILE%\"\r\n" +
                "start \"\" /min cmd /c \"ping -n 2 127.0.0.1 >nul & rmdir /s /q \"" + dir + "\"\"\r\n" +
                "exit\r\n";
            File.WriteAllText(bat, content, System.Text.Encoding.Default);
        }

        private static void RegisterUninstall(string dir, string exe)
        {
            try
            {
                using (RegistryKey k = Registry.CurrentUser.CreateSubKey(
                    @"Software\Microsoft\Windows\CurrentVersion\Uninstall\" + AppName))
                {
                    k.SetValue("DisplayName", AppName);
                    k.SetValue("DisplayVersion", AppVersion);
                    k.SetValue("Publisher", Publisher);
                    k.SetValue("InstallLocation", dir);
                    k.SetValue("DisplayIcon", exe);
                    k.SetValue("UninstallString", Path.Combine(dir, "uninstall.bat"));
                    k.SetValue("NoModify", 1);
                    k.SetValue("NoRepair", 1);
                    k.SetValue("EstimatedSize", 130000);
                }
            }
            catch
            {
                // 注册卸载信息失败不阻塞安装
            }
        }
    }

    public class MainForm : Form
    {
        private readonly TextBox dirBox = new TextBox();
        private readonly CheckBox desktopBox = new CheckBox();
        private readonly CheckBox runBox = new CheckBox();
        private readonly Button nextButton = new Button();
        private readonly Button cancelButton = new Button();
        private readonly Button browseButton = new Button();
        private readonly Panel pageWelcome = new Panel();
        private readonly Panel pageOptions = new Panel();
        private readonly Panel pageProgress = new Panel();
        private readonly ProgressBar progress = new ProgressBar();
        private readonly Label statusLabel = new Label();
        private readonly Label resultLabel = new Label();
        private Panel[] pages;
        private int pageIndex;
        private bool installed;

        [STAThread]
        private static void Main(string[] args)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            if (args.Length >= 2 && args[0] == "/silent")
            {
                bool ok = Core.Install(args[1], false, s => { });
                Environment.Exit(ok ? 0 : 1);
            }
            Application.Run(new MainForm());
        }

        public MainForm()
        {
            Text = "GluePaw 1.0.0 安装";
            Font = new Font("Microsoft YaHei UI", 9F);
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            ClientSize = new Size(520, 320);
            StartPosition = FormStartPosition.CenterScreen;
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            BuildPages();
            pages = new[] { pageWelcome, pageOptions, pageProgress };
            ShowPage(0);
        }

        private void BuildPages()
        {
            // 第 1 页：欢迎
            Label w1 = new Label
            {
                Text = "欢迎使用 GluePaw 安装程序",
                Font = new Font(Font.FontFamily, 12F, FontStyle.Bold),
                Location = new Point(24, 24),
                AutoSize = true
            };
            Label w2 = new Label
            {
                Text = "本地加密、隐私优先的剪贴板历史管理器。\r\n\r\n" +
                       "· 所有数据保存在本机，程序不联网\r\n" +
                       "· 安装到当前用户目录，不需要管理员权限\r\n" +
                       "· 卸载会保留剪贴板历史与密钥",
                Location = new Point(24, 70),
                Size = new Size(460, 120)
            };
            pageWelcome.Controls.Add(w1);
            pageWelcome.Controls.Add(w2);

            // 第 2 页：安装位置
            Label l1 = new Label { Text = "安装位置", Location = new Point(24, 30), AutoSize = true };
            dirBox.Location = new Point(24, 54);
            dirBox.Size = new Size(380, 23);
            dirBox.Text = Core.DefaultDir;
            browseButton.Text = "浏览…";
            browseButton.Location = new Point(410, 53);
            browseButton.Size = new Size(70, 25);
            browseButton.Click += (s, e) =>
            {
                using (FolderBrowserDialog d = new FolderBrowserDialog())
                {
                    d.SelectedPath = dirBox.Text;
                    if (d.ShowDialog(this) == DialogResult.OK) dirBox.Text = d.SelectedPath;
                }
            };
            desktopBox.Text = "创建桌面快捷方式";
            desktopBox.Location = new Point(24, 100);
            desktopBox.AutoSize = true;
            desktopBox.Checked = true;
            Label l2 = new Label
            {
                Text = "安装到当前用户目录（%LOCALAPPDATA%\\Programs\\GluePaw），无需管理员权限。",
                Location = new Point(24, 140),
                Size = new Size(460, 40)
            };
            pageOptions.Controls.Add(l1);
            pageOptions.Controls.Add(dirBox);
            pageOptions.Controls.Add(browseButton);
            pageOptions.Controls.Add(desktopBox);
            pageOptions.Controls.Add(l2);

            // 第 3 页：进度
            statusLabel.Location = new Point(24, 40);
            statusLabel.Size = new Size(460, 30);
            progress.Location = new Point(24, 80);
            progress.Size = new Size(460, 22);
            progress.Style = ProgressBarStyle.Marquee;
            progress.MarqueeAnimationSpeed = 30;
            resultLabel.Location = new Point(24, 130);
            resultLabel.Size = new Size(460, 80);
            pageProgress.Controls.Add(statusLabel);
            pageProgress.Controls.Add(progress);
            pageProgress.Controls.Add(resultLabel);

            // 底部按钮
            nextButton.Text = "下一步";
            nextButton.Location = new Point(320, 8);
            nextButton.Size = new Size(85, 27);
            nextButton.Click += OnNext;
            cancelButton.Text = "取消";
            cancelButton.Location = new Point(412, 8);
            cancelButton.Size = new Size(85, 27);
            cancelButton.Click += (s, e) => Close();

            // 按钮区（固定在底部，避免被页面面板遮挡）
            Panel bottom = new Panel { Dock = DockStyle.Bottom, Height = 46 };
            bottom.Controls.Add(nextButton);
            bottom.Controls.Add(cancelButton);
            Controls.Add(bottom);
            pageWelcome.Dock = DockStyle.Fill;
            pageOptions.Dock = DockStyle.Fill;
            pageProgress.Dock = DockStyle.Fill;
            Controls.Add(pageWelcome);
            Controls.Add(pageOptions);
            Controls.Add(pageProgress);
        }

        private void ShowPage(int index)
        {
            foreach (Panel p in pages) p.Visible = false;
            pageIndex = index;
            pages[index].Visible = true;
            pages[index].BringToFront();
            nextButton.Enabled = index != 2 || installed;
            if (index == 2)
            {
                cancelButton.Visible = false;
                if (installed)
                {
                    nextButton.Text = "完成";
                    runBox.Text = "立即运行 GluePaw";
                    runBox.Checked = true;
                    runBox.Location = new Point(24, 240);
                    runBox.AutoSize = true;
                    pageProgress.Controls.Add(runBox);
                }
            }
            else
            {
                cancelButton.Visible = true;
                nextButton.Text = index == 0 ? "下一步" : "安装";
            }
        }

        private void OnNext(object sender, EventArgs e)
        {
            if (pageIndex == 0)
            {
                ShowPage(1);
                return;
            }
            if (pageIndex == 1)
            {
                string dir = dirBox.Text.Trim();
                if (dir.Length == 0)
                {
                    MessageBox.Show(this, "请选择安装位置。", "GluePaw");
                    return;
                }
                nextButton.Enabled = false;
                cancelButton.Enabled = false;
                ShowPage(2);
                System.Threading.ThreadPool.QueueUserWorkItem(_ =>
                {
                    BeginInvoke((Action)(() => statusLabel.Text = "准备安装…"));
                    bool ok = Core.Install(dir, desktopBox.Checked, msg =>
                    {
                        try { BeginInvoke((Action)(() => statusLabel.Text = msg)); }
                        catch { }
                    });
                    BeginInvoke((Action)(() =>
                    {
                        installed = ok;
                        progress.Style = ProgressBarStyle.Blocks;
                        progress.Value = ok ? 100 : 0;
                        statusLabel.Text = ok ? "安装完成" : "安装失败";
                        resultLabel.Text = ok
                            ? "GluePaw 已安装到：\r\n" + dir +
                              "\r\n\r\n完成后可在开始菜单或桌面找到 GluePaw，按 Ctrl + Alt + V 唤出界面。"
                            : "安装未完成，请重试或检查目标目录的写入权限。";
                        nextButton.Enabled = true;
                        ShowPage(2);
                    }));
                });
                return;
            }
            if (pageIndex == 2 && installed)
            {
                if (runBox.Checked)
                {
                    try
                    {
                        Process.Start(new ProcessStartInfo(Path.Combine(dirBox.Text.Trim(), Core.ExeName))
                        {
                            WorkingDirectory = dirBox.Text.Trim()
                        });
                    }
                    catch { }
                }
                Close();
            }
        }
    }
}
