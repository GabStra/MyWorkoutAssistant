# Recurring workout prescriptions

Recurring sessions group related workout prescriptions in a plan. Each family advances independently; the app never advances it by calendar week. You can always open any prescription manually.

## Start and manage a session

1. Open **Workouts**, choose a plan, and open the workout to repeat.
2. In the workout's **More** menu, tap **Start recurring session**. This creates the first prescription and enables last-working-load carry for eligible exercises.
3. The workouts list shows one card for each recurring session. Open the session to see its prescriptions, suggested next step, and manual choices. From that session view, use **Manage prescriptions** to rename the family, edit each prescription label, move it up or down, add an existing workout from the same plan, or detach a prescription.
4. **Move up** and **Move down** save the order immediately and renumber the family. Save or discard any unsaved label or number edits before moving. Detaching a prescription keeps the existing workout and exercise history.
5. Detaching removes the recurring link and exercise tracks from that workout. Its existing workout and exercise history stays in the history screens.

To add a new plan family, create a workout in the plan, open it, and choose **Start recurring session** from **More**. To edit a plan's name or guidance setting, open the app menu, choose **Plans**, then edit the plan. This route is available even when there is only one plan. **Suggest the next recurring prescription** is on by default and can be switched off per plan. The setting is included in full-store backups and workout-plan packages.

## Add the next prescription

Choose **Add next prescription** in the family header. The app clones the highest-numbered prescription, keeps its exercise history tracks and load policy, creates new workout, exercise, and set identities, and opens the new workout.

From the new workout, open an exercise, then add or edit its sets to change the planned set count and reps. Exercise notes and effort settings remain available in the existing exercise editor. The exercise’s rep range is descriptive; changing it alone does not change the fixed reps in each set.

Prescription labels are descriptive, such as “Week 1”; the app does not infer a week or schedule from the label or number.

## Last-used loads

For eligible loaded-weight and bodyweight exercises, the per-exercise load policy offers three choices:

- **Automatic** keeps the legacy behavior, including automatic progression and calibration.
- **Prescribed weight** uses the current prescription's stored load and reps as the target. It does not carry or replace values from history and bypasses automatic progression and calibration execution. Completed actual performance is recorded, but does not change the next prescription's target. This mode can be used without a linked history track.
- **Last working load** shows the load and reps from the last completed matching session and carries that session's working load into a matching set. Starting a recurring session selects this policy by default for eligible exercises; you can change it per exercise.

History controls also let you keep a separate track, link a compatible exercise track in the family, or unlink it. Newly attached workouts start with separate tracks until you link them.

Last-load carry applies to exercises whose working sets are `WeightSet` or `BodyWeightSet` (rest sets are allowed). It does not apply to rep-only, timed, endurance, running, or other set types. In Last working load mode, calibration and active progression take precedence over a carried load. Prescribed reps stay with the current workout’s sets; historical reps are shown for reference and are not copied over.

## Next-prescription guidance

When enabled for the parent plan, the list marks the prescription after the latest normally completed prescription in that family. Completing a later prescription moves the suggestion to the step after that workout; the app does not mark earlier steps complete. At the end, it offers **Repeat sequence**. Turning guidance off hides the suggestion while leaving each prescription available for manual selection and keeping last-used load history available.
