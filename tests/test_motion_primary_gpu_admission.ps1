$ErrorActionPreference = 'Stop'
$errors = $null; $tokens = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot '../scripts/run_exercise_motion_workout_plan.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors -join "`n") }
$owner = $ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-MotionPrimaryGpuAvailable'}, $true)
Invoke-Expression $owner.Extent.Text
function Get-Process { param($Name) [pscustomobject]@{Id=123} }
function Get-Counter { param($Counter) [pscustomobject]@{CounterSamples=@([pscustomobject]@{InstanceName=$script:instance; CookedValue=4GB})} }
$script:instance='pid_123_luid_0_phys_0'
$blocked=$false
try { Assert-MotionPrimaryGpuAvailable } catch { $blocked=$_.Exception.Message -like '*PID 123*' }
if (-not $blocked) { throw 'GPU-resident competing server was admitted' }
$script:instance='pid_123_luid_0_phys_1'
Assert-MotionPrimaryGpuAvailable
$script:instance='pid_999_luid_0_phys_0'
Assert-MotionPrimaryGpuAvailable
'GPU residency admission checks passed'
