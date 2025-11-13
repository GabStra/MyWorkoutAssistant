package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import java.time.DayOfWeek
import java.time.LocalDate

object ScheduleConflictChecker {
    
    /**
     * Represents a conflict between two schedules
     */
    data class ScheduleConflict(
        val schedule1: WorkoutSchedule,
        val schedule2: WorkoutSchedule
    )
    
    /**
     * Checks for conflicts between new schedules and existing schedules.
     * Also checks for conflicts within the new schedules list itself.
     * 
     * @param newSchedules The schedules being added/updated
     * @param existingSchedules The schedules already in the database
     * @return List of conflicts found, empty if none
     */
    fun checkScheduleConflicts(
        newSchedules: List<WorkoutSchedule>,
        existingSchedules: List<WorkoutSchedule>
    ): List<ScheduleConflict> {
        val conflicts = mutableListOf<ScheduleConflict>()
        
        // Check conflicts within new schedules
        for (i in newSchedules.indices) {
            for (j in (i + 1) until newSchedules.size) {
                if (schedulesConflict(newSchedules[i], newSchedules[j])) {
                    conflicts.add(ScheduleConflict(newSchedules[i], newSchedules[j]))
                }
            }
        }
        
        // Check conflicts between new schedules and existing schedules
        for (newSchedule in newSchedules) {
            for (existingSchedule in existingSchedules) {
                // Skip if it's the same schedule (by ID) - allows updating without false conflicts
                if (newSchedule.id == existingSchedule.id) {
                    continue
                }
                if (schedulesConflict(newSchedule, existingSchedule)) {
                    conflicts.add(ScheduleConflict(newSchedule, existingSchedule))
                }
            }
        }
        
        return conflicts
    }
    
    /**
     * Checks if two schedules conflict with each other.
     * Two schedules conflict if they have the same time (hour and minute)
     * and overlap in their day/date configuration.
     */
    fun schedulesConflict(schedule1: WorkoutSchedule, schedule2: WorkoutSchedule): Boolean {
        // Must have the same time
        if (schedule1.hour != schedule2.hour || schedule1.minute != schedule2.minute) {
            return false
        }
        
        // Check day overlap
        return schedulesOverlapInDays(schedule1, schedule2)
    }
    
    /**
     * Checks if two schedules overlap in their day/date configuration.
     * They overlap if:
     * 1. Both have the same specificDate, OR
     * 2. Both have daysOfWeek with overlapping bits, OR
     * 3. One has specificDate and the other's daysOfWeek includes that day
     */
    private fun schedulesOverlapInDays(schedule1: WorkoutSchedule, schedule2: WorkoutSchedule): Boolean {
        // Case 1: Both have specific dates - check if they're the same
        if (schedule1.specificDate != null && schedule2.specificDate != null) {
            return schedule1.specificDate == schedule2.specificDate
        }
        
        // Case 2: Both have daysOfWeek - check for overlapping bits
        if (schedule1.specificDate == null && schedule2.specificDate == null &&
            schedule1.daysOfWeek > 0 && schedule2.daysOfWeek > 0) {
            return (schedule1.daysOfWeek and schedule2.daysOfWeek) != 0
        }
        
        // Case 3: One has specificDate, the other has daysOfWeek
        val specificDateSchedule = if (schedule1.specificDate != null) schedule1 else schedule2
        val daysOfWeekSchedule = if (schedule1.specificDate != null) schedule2 else schedule1
        
        if (specificDateSchedule.specificDate != null && daysOfWeekSchedule.daysOfWeek > 0) {
            val dayOfWeek = specificDateSchedule.specificDate!!.dayOfWeek
            val dayBit = dayOfWeekToBit(dayOfWeek)
            return (daysOfWeekSchedule.daysOfWeek and dayBit) != 0
        }
        
        return false
    }
    
    /**
     * Converts a DayOfWeek to the corresponding bit value used in daysOfWeek.
     * bit 0 = Sunday (value 1)
     * bit 1 = Monday (value 2)
     * bit 2 = Tuesday (value 4)
     * bit 3 = Wednesday (value 8)
     * bit 4 = Thursday (value 16)
     * bit 5 = Friday (value 32)
     * bit 6 = Saturday (value 64)
     */
    private fun dayOfWeekToBit(dayOfWeek: DayOfWeek): Int {
        // DayOfWeek ordinal: MONDAY=0, TUESDAY=1, ..., SUNDAY=6
        // We need: Sunday=0, Monday=1, ..., Saturday=6
        // So we need to map: MONDAY(0)->1, TUESDAY(1)->2, ..., SUNDAY(6)->0
        val adjustedValue = when (dayOfWeek) {
            DayOfWeek.SUNDAY -> 0
            DayOfWeek.MONDAY -> 1
            DayOfWeek.TUESDAY -> 2
            DayOfWeek.WEDNESDAY -> 3
            DayOfWeek.THURSDAY -> 4
            DayOfWeek.FRIDAY -> 5
            DayOfWeek.SATURDAY -> 6
        }
        return 1 shl adjustedValue
    }
    
    /**
     * Formats a conflict message for display to the user.
     */
    fun formatConflictMessage(conflicts: List<ScheduleConflict>): String {
        if (conflicts.isEmpty()) {
            return ""
        }
        
        val conflictDetails = conflicts.take(3).joinToString(", ") { conflict ->
            val s1 = formatScheduleTime(conflict.schedule1)
            val s2 = formatScheduleTime(conflict.schedule2)
            "$s1 and $s2"
        }
        
        val moreText = if (conflicts.size > 3) " and ${conflicts.size - 3} more" else ""
        return "Cannot schedule workouts at the same time: $conflictDetails$moreText"
    }
    
    /**
     * Formats a schedule's time and day information for display.
     */
    private fun formatScheduleTime(schedule: WorkoutSchedule): String {
        val timeStr = "${schedule.hour}:${schedule.minute.toString().padStart(2, '0')}"
        val dayStr = when {
            schedule.specificDate != null -> schedule.specificDate.toString()
            schedule.daysOfWeek > 0 -> "recurring"
            else -> "unknown"
        }
        return "$timeStr ($dayStr)"
    }
}

