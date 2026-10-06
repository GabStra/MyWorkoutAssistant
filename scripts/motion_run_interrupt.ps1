# Shared Ctrl+C handling for exercise-motion PowerShell wrappers.
# Uses a C# ConsoleCancelEventHandler so the signal thread never invokes a PowerShell scriptblock.
# Nested wrappers (library -> workout-plan pwsh) should register -Silent so only the inner
# process prints the Ctrl+C message. Windows delivers CTRL_C_EVENT to every process in the
# console group, so both would otherwise acknowledge the same keypress.

if (-not ("MotionRunInterrupt" -as [type])) {
    Add-Type @"
using System;
using System.Threading;

public static class MotionRunInterrupt
{
    private static int _cancelRequested;
    private static int _acknowledged;
    private static int _handlerRegistered;
    private static int _silent;

    public static bool CancelRequested
    {
        get { return Interlocked.CompareExchange(ref _cancelRequested, 0, 0) != 0; }
    }

    public static bool Acknowledged
    {
        get { return Interlocked.CompareExchange(ref _acknowledged, 0, 0) != 0; }
    }

    public static bool Silent
    {
        get { return Interlocked.CompareExchange(ref _silent, 0, 0) != 0; }
    }

    public static void RegisterOnce()
    {
        RegisterOnce(false);
    }

    public static void RegisterOnce(bool silent)
    {
        if (silent)
        {
            Interlocked.Exchange(ref _silent, 1);
        }

        if (Interlocked.CompareExchange(ref _handlerRegistered, 1, 0) != 0)
        {
            return;
        }

        Console.CancelKeyPress += OnCancelKeyPress;
    }

    public static bool TryAcknowledge()
    {
        return Interlocked.CompareExchange(ref _acknowledged, 1, 0) == 0;
    }

    private static void OnCancelKeyPress(object sender, ConsoleCancelEventArgs e)
    {
        e.Cancel = true;
        Interlocked.Exchange(ref _cancelRequested, 1);
        if (Silent)
        {
            Interlocked.Exchange(ref _acknowledged, 1);
            return;
        }
        if (!TryAcknowledge())
        {
            return;
        }
        try
        {
            Console.Error.WriteLine("");
            Console.Error.WriteLine("Ctrl+C received. Stopping the motion run; workers and GPU processes may take a few seconds to exit.");
            Console.Error.Flush();
        }
        catch
        {
        }
    }
}
"@
}

function Write-MotionInterruptReceived {
    if ([MotionRunInterrupt]::Silent) {
        return
    }
    if (-not [MotionRunInterrupt]::TryAcknowledge()) {
        return
    }
    $message = "Ctrl+C received. Stopping the motion run; workers and GPU processes may take a few seconds to exit."
    try {
        [Console]::Error.WriteLine("")
        [Console]::Error.WriteLine($message)
        [Console]::Error.Flush()
    } catch {
        Write-Host ""
        Write-Host $message -ForegroundColor Yellow
    }
}

function Test-MotionRunCancelRequested {
    return [MotionRunInterrupt]::CancelRequested
}

function Register-MotionInterruptHandler {
    param([switch]$Silent)
    [MotionRunInterrupt]::RegisterOnce([bool]$Silent)
}

function Exit-IfMotionRunInterrupted {
    param([int]$ExitCode = $LASTEXITCODE)
    if ((Test-MotionRunCancelRequested) -or $ExitCode -eq 130) {
        Write-MotionInterruptReceived
        exit 130
    }
}

Register-MotionInterruptHandler
