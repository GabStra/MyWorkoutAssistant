# Shared Ctrl+C handling for exercise-motion PowerShell wrappers.
# Uses a C# ConsoleCancelEventHandler so the signal thread never invokes a PowerShell scriptblock.

if (-not ("MotionRunInterrupt" -as [type])) {
    Add-Type @"
using System;
using System.Threading;

public static class MotionRunInterrupt
{
    private static int _cancelRequested;
    private static int _acknowledged;
    private static int _handlerRegistered;

    public static bool CancelRequested
    {
        get { return Interlocked.CompareExchange(ref _cancelRequested, 0, 0) != 0; }
    }

    public static bool Acknowledged
    {
        get { return Interlocked.CompareExchange(ref _acknowledged, 0, 0) != 0; }
    }

    public static void RegisterOnce()
    {
        if (Interlocked.CompareExchange(ref _handlerRegistered, 1, 0) != 0)
        {
            return;
        }

        Console.CancelKeyPress += OnCancelKeyPress;
    }

    private static void OnCancelKeyPress(object sender, ConsoleCancelEventArgs e)
    {
        e.Cancel = true;
        Interlocked.Exchange(ref _cancelRequested, 1);
        if (Interlocked.CompareExchange(ref _acknowledged, 1, 0) == 0)
        {
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
}
"@
}

function Write-MotionInterruptReceived {
    if ([MotionRunInterrupt]::Acknowledged) {
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
    [MotionRunInterrupt]::RegisterOnce()
}

function Exit-IfMotionRunInterrupted {
    param([int]$ExitCode = $LASTEXITCODE)
    if ((Test-MotionRunCancelRequested) -or $ExitCode -eq 130) {
        Write-MotionInterruptReceived
        exit 130
    }
}

Register-MotionInterruptHandler
