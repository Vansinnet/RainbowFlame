using RainbowFlame.Installer.Core;

namespace RainbowFlame.Installer;

public sealed class MainForm : Form
{
    private readonly TextBox folder = new() { Dock = DockStyle.Fill };
    private readonly Label status = new() { AutoSize = false, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft };
    private readonly Button install = new() { Text = "Install", AutoSize = true };
    private readonly Button repair = new() { Text = "Repair", AutoSize = true };
    private readonly Button repairAfterUpdate = new() { Text = "Repair after update", AutoSize = true };
    private readonly Button uninstall = new() { Text = "Uninstall", AutoSize = true };
    private readonly Button browse = new() { Text = "Browse...", AutoSize = true };
    private readonly InstallerEngine engine;

    public MainForm()
    {
        Text = "RainbowFlame Installer";
        MinimumSize = new Size(680, 280);
        Size = new Size(760, 320);
        StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Segoe UI", 10);
        var payload = FindPayload();
        engine = new InstallerEngine(payload);

        var heading = new Label { Text = "RainbowFlame", Font = new Font(Font.FontFamily, 22, FontStyle.Bold), AutoSize = true };
        var description = new Label
        {
            Text = "Safe installer for Steam build 24735202 / Darktide 1.3.770.210. " +
                   "After a game update, Repair after update can restore compatible files without reinstalling. " +
                   "Darktide must be closed. DML and DMF must already be installed.",
            AutoSize = true, MaximumSize = new Size(700, 0)
        };
        var picker = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 2 };
        picker.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        picker.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        picker.Controls.Add(folder, 0, 0); picker.Controls.Add(browse, 1, 0);
        var actions = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true };
        actions.Controls.AddRange(new Control[] { install, repair, repairAfterUpdate, uninstall });
        var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(24), RowCount = 6, ColumnCount = 1 };
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.Controls.Add(heading); layout.Controls.Add(description); layout.Controls.Add(picker); layout.Controls.Add(actions); layout.Controls.Add(status);
        Controls.Add(layout);

        browse.Click += (_, _) => PickFolder();
        install.Click += async (_, _) => await Run(InstallerAction.Install);
        repair.Click += async (_, _) => await Run(InstallerAction.Repair);
        repairAfterUpdate.Click += async (_, _) => await Run(InstallerAction.RepairAfterUpdate);
        uninstall.Click += async (_, _) => await Run(InstallerAction.Uninstall);
        folder.Text = GameDiscovery.FindGameRoots().FirstOrDefault() ?? "";
        status.Text = folder.Text.Length == 0 ? "Select the Darktide installation folder." : "Ready. No files are changed until you choose an action.";
    }

    private void PickFolder()
    {
        using var dialog = new FolderBrowserDialog { Description = "Select the Warhammer 40,000 DARKTIDE folder", UseDescriptionForTitle = true };
        if (dialog.ShowDialog(this) == DialogResult.OK) folder.Text = dialog.SelectedPath;
    }

    private async Task Run(InstallerAction action)
    {
        if (action == InstallerAction.RepairAfterUpdate && MessageBox.Show(this,
                "Use this after a Darktide update has overwritten RainbowFlame files. " +
                "The installer will accept a changed game version only when every managed file has a known safe hash. " +
                "If Fatshark changed a required bundle, it will stop before writing and require a new RainbowFlame release.",
                "RainbowFlame update repair", MessageBoxButtons.OKCancel, MessageBoxIcon.Information) != DialogResult.OK)
            return;
        SetBusy(true);
        status.Text = action == InstallerAction.RepairAfterUpdate
            ? "Repair after update in progress. Preflighting every managed file before writing..."
            : $"{action} in progress. Verifying every input and output...";
        try
        {
            var result = await Task.Run(() => engine.Execute(folder.Text, action));
            status.Text = result.Message;
            MessageBox.Show(this, result.Message, "RainbowFlame", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception error)
        {
            status.Text = error.Message;
            MessageBox.Show(this, error.Message, "RainbowFlame stopped safely", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally { SetBusy(false); }
    }

    private void SetBusy(bool busy)
    {
        install.Enabled = repair.Enabled = repairAfterUpdate.Enabled = uninstall.Enabled = browse.Enabled = folder.Enabled = !busy;
        UseWaitCursor = busy;
    }

    private static string FindPayload()
    {
        var candidates = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "payload"),
            Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "payload"))
        };
        return candidates.FirstOrDefault(path => File.Exists(Path.Combine(path, "manifest.json")))
            ?? candidates[0];
    }
}
