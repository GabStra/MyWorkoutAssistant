package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.RestHistoryDao
import com.gabstra.myworkoutassistant.shared.RestHistoryScope
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.WeeklyProgressResolver
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.formatNumber
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.WarmupPlanner
import com.gabstra.myworkoutassistant.shared.workout.history.SessionTimelineItem
import com.gabstra.myworkoutassistant.shared.workout.history.mergeSessionTimeline
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.time.temporal.TemporalAdjusters
import java.util.Calendar
import java.util.UUID
import kotlin.math.abs
import kotlin.math.roundToInt

/** Parallel export chunk size (sessions / histories / exercise blocks processed per coroutine batch). */
private const val EXPORT_RENDER_BATCH_SIZE = 16

private val EXPORT_HISTORY_OPEN_START: LocalDate = LocalDate.of(1970, 1, 1)
private val EXPORT_HISTORY_OPEN_END: LocalDate = LocalDate.of(9999, 12, 31)

sealed class WorkoutDataMarkdownResult {
    data class Success(val markdown: String) : WorkoutDataMarkdownResult()
    data class Failure(val message: String) : WorkoutDataMarkdownResult()
}

sealed class WorkoutDataMarkdownWriteResult {
    object Success : WorkoutDataMarkdownWriteResult()
    data class Failure(val message: String) : WorkoutDataMarkdownWriteResult()
}

private data class SessionExportBlock(
    val index: Int,
    val history: WorkoutHistory,
    val markdown: String?,
    val failureMessage: String?,
)

private data class ExerciseSummaryExportBlock(
    val exercise: Exercise,
    val markdown: String?,
    val failureMessage: String?,
)

private data class WeekExportGroup(
    val weekStart: LocalDate,
    val weekEnd: LocalDate,
    val histories: List<WorkoutHistory>,
)

private data class ExerciseSessionExportSection(
    val label: String,
    val exercise: Exercise,
    val setHistories: List<SetHistory>,
    val rests: List<RestHistory>,
)

private data class RestExportEntry(
    val plannedSeconds: Int?,
    val actualSeconds: Int?,
)

sealed class WorkoutDataExportRange {
    abstract val label: String
    abstract val fileSlug: String

    open fun startDate(referenceDate: LocalDate): LocalDate? = null

    open fun endDate(referenceDate: LocalDate): LocalDate? = null

    fun includes(date: LocalDate, referenceDate: LocalDate): Boolean {
        val startDate = startDate(referenceDate)
        val endDate = endDate(referenceDate)
        return (startDate == null || !date.isBefore(startDate)) &&
            (endDate == null || !date.isAfter(endDate))
    }

    object ALL : WorkoutDataExportRange() {
        override val label: String = "All data"
        override val fileSlug: String = "all"
    }

    object LAST_WEEK : WorkoutDataExportRange() {
        override val label: String = "Last week"
        override val fileSlug: String = "last_week"
        override fun startDate(referenceDate: LocalDate): LocalDate = referenceDate.minusWeeks(1)
    }

    object LAST_MONTH : WorkoutDataExportRange() {
        override val label: String = "Last month"
        override val fileSlug: String = "last_month"
        override fun startDate(referenceDate: LocalDate): LocalDate = referenceDate.minusMonths(1)
    }

    object LAST_THREE_MONTHS : WorkoutDataExportRange() {
        override val label: String = "Last 3 months"
        override val fileSlug: String = "last_3_months"
        override fun startDate(referenceDate: LocalDate): LocalDate = referenceDate.minusMonths(3)
    }

    data class Custom(
        val customStartDate: LocalDate,
        val customEndDate: LocalDate,
    ) : WorkoutDataExportRange() {
        init {
            require(!customEndDate.isBefore(customStartDate)) {
                "customEndDate must be on or after customStartDate"
            }
        }

        override val label: String = "$customStartDate to $customEndDate"
        override val fileSlug: String = "custom_${customStartDate}_to_${customEndDate}"

        override fun startDate(referenceDate: LocalDate): LocalDate = customStartDate

        override fun endDate(referenceDate: LocalDate): LocalDate = customEndDate
    }
}

suspend fun buildWorkoutDataMarkdown(
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workoutStore: WorkoutStore,
    exportedAt: LocalDateTime = LocalDateTime.now(),
    exportRange: WorkoutDataExportRange = WorkoutDataExportRange.ALL,
    onProgress: suspend (String) -> Unit = {},
): WorkoutDataMarkdownResult {
    val markdown = StringBuilder()
    return when (
        val result = writeWorkoutDataMarkdown(
            workoutHistoryDao = workoutHistoryDao,
            setHistoryDao = setHistoryDao,
            restHistoryDao = restHistoryDao,
            exerciseSessionProgressionDao = exerciseSessionProgressionDao,
            workoutStore = workoutStore,
            exportedAt = exportedAt,
            exportRange = exportRange,
            appendMarkdown = { markdown.append(it) },
            onProgress = onProgress
        )
    ) {
        is WorkoutDataMarkdownWriteResult.Success -> WorkoutDataMarkdownResult.Success(markdown.toString())
        is WorkoutDataMarkdownWriteResult.Failure -> WorkoutDataMarkdownResult.Failure(result.message)
    }
}

suspend fun writeWorkoutDataMarkdown(
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workoutStore: WorkoutStore,
    exportedAt: LocalDateTime = LocalDateTime.now(),
    exportRange: WorkoutDataExportRange = WorkoutDataExportRange.ALL,
    appendMarkdown: suspend (String) -> Unit,
    onProgress: suspend (String) -> Unit = {},
): WorkoutDataMarkdownWriteResult {
    onProgress("Preparing workout data export...")
    val userAge = Calendar.getInstance().get(Calendar.YEAR) - workoutStore.birthDateYear
    val referenceDate = exportedAt.toLocalDate()
    val rangeStartDate = exportRange.startDate(referenceDate)
    val rangeEndDate = exportRange.endDate(referenceDate)
    val completedHistories = if (rangeStartDate == null && rangeEndDate == null) {
        workoutHistoryDao.getAllWorkoutHistoriesByIsDone()
    } else {
        workoutHistoryDao.getCompletedWorkoutHistoriesBetweenInclusive(
            startInclusive = rangeStartDate ?: EXPORT_HISTORY_OPEN_START,
            endInclusive = rangeEndDate ?: EXPORT_HISTORY_OPEN_END,
        )
    }
        .filter { history -> exportRange.includes(history.date, referenceDate) }
        .sortedWith(compareBy<WorkoutHistory>({ it.startTime }, { it.date }, { it.time }, { it.id.toString() }))
    val exercises = collectExercisesForExport(workoutStore)

    appendMarkdown("# My Workout Assistant Export\n\n")
    appendMarkdown("- Exported at: ${exportedAt.format(DateTimeFormatter.ISO_LOCAL_DATE_TIME)}\n")
    appendMarkdown(
        "- ${
            when {
                rangeStartDate != null && rangeEndDate != null ->
                    "Session dates included: $rangeStartDate to $rangeEndDate"
                rangeStartDate != null ->
                    "Session dates from $rangeStartDate (${exportRange.label})"
                rangeEndDate != null ->
                    "Session dates through $rangeEndDate (${exportRange.label})"
                else ->
                    "Session dates: all completed sessions (${exportRange.label})"
            }
        }\n"
    )
    appendMarkdown("- Completed sessions: ${completedHistories.size}\n")
    appendMarkdown("- Exercises in plan: ${exercises.size}\n")
    appendMarkdown(
        "- Time format: clock-style `mm:ss` under 1 hour; `hh:mm:ss` for 1 hour or longer " +
            "(session duration, timed sets, rests, set execution spans).\n\n"
    )
    appendMarkdown(
        "Privacy note: this file can include profile data, body weight, heart-rate summaries, " +
            "exercise notes, session timelines, and progression history. Share it only with tools you trust.\n\n"
    )

    appendMarkdown("## Athlete Info\n\n")
    appendMarkdown(buildString { appendLlmExportContextMarkdown(this, workoutStore, userAge) })

    onProgress("Adding workout plan and equipment...")
    appendPlanReferenceMarkdown(appendMarkdown, workoutStore)

    onProgress("Processing workout history...")
    appendWeeklyTrainingLogMarkdown(
        appendMarkdown = appendMarkdown,
        histories = completedHistories,
        workoutHistoryDao = workoutHistoryDao,
        setHistoryDao = setHistoryDao,
        restHistoryDao = restHistoryDao,
        exerciseSessionProgressionDao = exerciseSessionProgressionDao,
        workoutStore = workoutStore
    )

    onProgress("Finishing Markdown export...")
    return WorkoutDataMarkdownWriteResult.Success
}

private suspend fun appendPlanReferenceMarkdown(
    appendMarkdown: suspend (String) -> Unit,
    workoutStore: WorkoutStore,
) {
    appendMarkdown("## Plan Reference\n\n")
    appendMarkdown("### How loads are reported\n\n")
    appendMarkdown(
        "- For exercises that use a **body-weight percentage**, baseline moving load is " +
            "`profile weight (kg) × exercise % ÷ 100`. Logged sets describe **extra load vs that baseline** " +
            "and **total moving load** (baseline plus added equipment weight).\n\n"
    )
    val activeWorkouts = workoutStore.workouts
        .filter { it.isActive && it.enabled }
        .distinctBy { it.globalId }
        .sortedWith(compareBy<Workout> { it.order }.thenBy { it.name })

    if (activeWorkouts.isEmpty()) {
        appendMarkdown("No workouts configured.\n\n")
    } else {
        appendMarkdown("### Active Workouts\n\n")
        val withWeeklyTarget = activeWorkouts.filter { (it.timesCompletedInAWeek ?: 0) > 0 }
        val withoutWeeklyTarget = activeWorkouts.filter { (it.timesCompletedInAWeek ?: 0) <= 0 }
        withWeeklyTarget.forEach { workout ->
            val weeklyTarget = workout.timesCompletedInAWeek!!
            appendMarkdown("- ${workout.name}: $weeklyTarget/week\n")
        }
        if (withoutWeeklyTarget.isNotEmpty()) {
            val names = withoutWeeklyTarget.map { it.name }
            appendMarkdown(
                "- No weekly target (${names.size} workouts): ${names.joinToString(", ")}\n"
            )
        }
        appendMarkdown("\n")
    }

    if (workoutStore.equipments.isNotEmpty()) {
        appendMarkdown("### Equipment Reference\n\n")
        workoutStore.equipments
            .sortedBy { it.name }
            .forEach { equipment ->
                appendMarkdown("- ${equipment.name}: ${equipment.type}")
                compactAvailableLoads(equipment)?.let { loads ->
                    appendMarkdown(" | available loads: $loads")
                }
                appendMarkdown("\n")
            }
        appendMarkdown("\n")
    }
}

private suspend fun appendWeeklyTrainingLogMarkdown(
    appendMarkdown: suspend (String) -> Unit,
    histories: List<WorkoutHistory>,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workoutStore: WorkoutStore,
) {
    appendMarkdown("## Weekly Training Log\n\n")
    if (histories.isEmpty()) {
        appendMarkdown("No completed workout sessions found.\n\n")
        return
    }

    val weekGroups = histories
        .groupBy { history -> startOfWeek(history.date) }
        .toSortedMap()
        .map { (weekStart, weekHistories) ->
            WeekExportGroup(
                weekStart = weekStart,
                weekEnd = endOfWeek(weekStart),
                histories = weekHistories.sortedWith(
                    compareBy<WorkoutHistory>({ it.startTime }, { it.date }, { it.time }, { it.id.toString() })
                )
            )
        }
    val skippedSessions = mutableListOf<String>()
    var sessionIndex = 0

    weekGroups.forEach { week ->
        appendMarkdown("### Week ${week.weekStart} to ${week.weekEnd}\n\n")
        appendWeeklyProgressMarkdown(appendMarkdown, week, workoutStore)
        appendMarkdown("#### Sessions\n\n")

        week.histories.chunked(EXPORT_RENDER_BATCH_SIZE).forEachIndexed { batchIndex, batch ->
            val batchStartIndex = sessionIndex + batchIndex * EXPORT_RENDER_BATCH_SIZE
            val renderedSessions = coroutineScope {
                batch.mapIndexed { indexInBatch, history ->
                    async {
                        renderCompactSessionExportBlock(
                            index = batchStartIndex + indexInBatch,
                            history = history,
        workoutHistoryDao = workoutHistoryDao,
        setHistoryDao = setHistoryDao,
        restHistoryDao = restHistoryDao,
                            exerciseSessionProgressionDao = exerciseSessionProgressionDao,
                            workoutStore = workoutStore
                        )
                    }
                }.awaitAll()
            }
            renderedSessions.sortedBy { it.index }.forEach { block ->
                if (block.markdown != null) {
                    appendMarkdown("##### Session ${block.index + 1}: ${block.history.date} ${block.history.time}\n\n")
                    appendMarkdown(block.markdown.trim())
                    appendMarkdown("\n\n")
                } else {
                    skippedSessions += "${block.history.date} ${block.history.time}: ${block.failureMessage}"
                }
            }
        }
        sessionIndex += week.histories.size
    }
    appendSkippedItemsMarkdown(appendMarkdown, "Skipped sessions", skippedSessions)
}

private suspend fun appendWeeklyProgressMarkdown(
    appendMarkdown: suspend (String) -> Unit,
    week: WeekExportGroup,
    workoutStore: WorkoutStore,
) {
    val snapshot = WeeklyProgressResolver.resolveForWeek(
        workouts = workoutStore.workouts,
        workoutHistoriesInWeek = week.histories,
        weekStart = week.weekStart,
        weekEnd = week.weekEnd,
        weeklyProgressOverrides = workoutStore.weeklyProgressOverrides
    )

    appendMarkdown("#### Weekly Objective\n\n")
    appendMarkdown("- Objective progress: ${formatNumber(snapshot.objectiveProgress * 100.0)}%\n")
    if (snapshot.hasOverride) {
        val source = snapshot.effectiveOverrideWeekStart?.toString() ?: "unknown"
        appendMarkdown("- Weekly selection override active since: $source\n")
    }

    if (snapshot.weeklyWorkoutsByActualTarget.isEmpty()) {
        appendMarkdown("- No weekly workout objective configured.\n\n")
        return
    }

    snapshot.weeklyWorkoutsByActualTarget.forEach { (workout, actualTarget) ->
        val (actual, target) = actualTarget
        appendMarkdown("- ${workout.name}: achieved $actual / expected $target\n")
    }
    appendMarkdown("\n")
}

private suspend fun renderCompactSessionExportBlock(
    index: Int,
    history: WorkoutHistory,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workoutStore: WorkoutStore,
): SessionExportBlock {
    return try {
        val markdown = buildCompactSessionMarkdown(
            history = history,
            workoutHistoryDao = workoutHistoryDao,
            setHistoryDao = setHistoryDao,
            restHistoryDao = restHistoryDao,
            exerciseSessionProgressionDao = exerciseSessionProgressionDao,
            workoutStore = workoutStore
        )
        SessionExportBlock(
            index = index,
            history = history,
            markdown = markdown,
            failureMessage = null
        )
    } catch (exception: CancellationException) {
        throw exception
    } catch (exception: Exception) {
        SessionExportBlock(
            index = index,
            history = history,
            markdown = null,
            failureMessage = exception.message ?: "Unexpected session export error"
        )
    }
}

private suspend fun buildCompactSessionMarkdown(
    history: WorkoutHistory,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workoutStore: WorkoutStore,
): String {
    val workout = workoutStore.workouts.find { it.id == history.workoutId }
        ?: throw IllegalStateException("Workout definition not found")
    val userAge = Calendar.getInstance().get(Calendar.YEAR) - workoutStore.birthDateYear
    val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryIdOrdered(history.id)
    val restHistories = restHistoryDao.getByWorkoutHistoryIdOrdered(history.id)
    val progressionByExerciseId = exerciseSessionProgressionDao
        .getByWorkoutHistoryId(history.id)
        .associateBy { it.exerciseId }
    val markdown = StringBuilder()

    markdown.append("- Workout: ${workout.name}\n")
    markdown.append("- Duration: ${formatDurationForExport(history.duration)}\n")
    compactSessionHeartRateLine(history, workoutStore, userAge)?.let { line ->
        markdown.append("- Heart rate: $line\n")
    }
    if (workout.description.isNotBlank()) {
        markdown.append("- Notes: ${workout.description}\n")
    }
    markdown.append("\n")

    val sections = buildExerciseSessionSections(
        workout = workout,
        setHistories = setHistories,
        restHistories = restHistories
    )
    if (sections.isEmpty()) {
        markdown.append("No recorded exercise sets found.\n")
        return markdown.toString()
    }

    val sectionStartKeys = sections.associateWith { section -> earliestSectionSortKey(section) }
    val sectionEndKeys = sections.associateWith { section -> latestSectionSortKey(section) }
    val betweenComponentRests = restHistories
        .filter { it.scope == RestHistoryScope.BETWEEN_WORKOUT_COMPONENTS }
        .sortedWith(compareBy<RestHistory>({ it.executionSequence ?: UInt.MAX_VALUE }, { it.startTime }))
        .toMutableList()

    sections.forEachIndexed { index, section ->
        appendCompactExerciseSessionMarkdown(
            markdown = markdown,
            section = section,
            history = history,
            progressionByExerciseId = progressionByExerciseId,
            workoutStore = workoutStore,
            userAge = userAge
        )

        val currentSectionEnd = sectionEndKeys[section] ?: Long.MIN_VALUE
        val nextSectionSortKey = sections.getOrNull(index + 1)?.let { next ->
            sectionStartKeys[next] ?: UInt.MAX_VALUE.toLong()
        } ?: Long.MAX_VALUE
        while (betweenComponentRests.isNotEmpty()) {
            val candidate = betweenComponentRests.first()
            val candidateKey = candidate.executionSequence?.toLong() ?: Long.MAX_VALUE
            if (candidateKey >= nextSectionSortKey) break
            betweenComponentRests.removeAt(0)
            if (candidateKey <= currentSectionEnd) continue
            candidate.toRestExportEntry()?.toCompactRestText()?.let { restText ->
                markdown.append("- Rest after exercise: $restText\n")
            }
        }
    }

    betweenComponentRests.forEach { rest ->
        rest.toRestExportEntry()?.toCompactRestText()?.let { restText ->
            markdown.append("- Rest after exercise: $restText\n")
        }
    }
    return markdown.toString()
}

private fun earliestSectionSortKey(section: ExerciseSessionExportSection): Long {
    val setKey = section.setHistories
        .mapNotNull { set -> set.executionSequence?.toLong() }
        .minOrNull()
    val restKey = section.rests
        .filter { it.scope == RestHistoryScope.INTRA_EXERCISE }
        .mapNotNull { rest -> rest.executionSequence?.toLong() }
        .minOrNull()
    return minOf(setKey ?: Long.MAX_VALUE, restKey ?: Long.MAX_VALUE)
}

private fun latestSectionSortKey(section: ExerciseSessionExportSection): Long {
    val setKey = section.setHistories
        .mapNotNull { set -> set.executionSequence?.toLong() }
        .maxOrNull()
    val restKey = section.rests
        .filter { it.scope == RestHistoryScope.INTRA_EXERCISE }
        .mapNotNull { rest -> rest.executionSequence?.toLong() }
        .maxOrNull()
    return maxOf(setKey ?: Long.MIN_VALUE, restKey ?: Long.MIN_VALUE)
}

private fun buildExerciseSessionSections(
    workout: Workout,
    setHistories: List<SetHistory>,
    restHistories: List<RestHistory>,
): List<ExerciseSessionExportSection> {
    val sections = mutableListOf<ExerciseSessionExportSection>()
    val consumedSetIds = mutableSetOf<UUID>()

    workout.workoutComponents.forEach { component ->
        when (component) {
            is Exercise -> {
                val exerciseSets = setHistories
                    .filter { it.exerciseId == component.id && it.id !in consumedSetIds }
                    .sortedBy { it.order }
                if (exerciseSets.isNotEmpty()) {
                    consumedSetIds += exerciseSets.map { it.id }
                    sections += ExerciseSessionExportSection(
                        label = component.name,
                        exercise = component,
                        setHistories = exerciseSets,
                        rests = restHistories.filter { it.exerciseId == component.id }
                    )
                }
            }
            is Superset -> {
                component.exercises.forEach { exercise ->
                    val exerciseSets = setHistories
                        .filter {
                            it.exerciseId == exercise.id &&
                                it.supersetId == component.id &&
                                it.id !in consumedSetIds
                        }
                        .sortedWith(
                            compareBy<SetHistory>(
                                { it.executionSequence == null },
                                { it.executionSequence ?: UInt.MAX_VALUE },
                                { it.order }
                            )
                        )
                    if (exerciseSets.isNotEmpty()) {
                        consumedSetIds += exerciseSets.map { it.id }
                        sections += ExerciseSessionExportSection(
                            label = "Superset - ${exercise.name}",
                            exercise = exercise,
                            setHistories = exerciseSets,
                            rests = restHistories.filter { it.exerciseId == exercise.id }
                        )
                    }
                }
            }
            is Rest -> Unit
        }
    }

    val knownExerciseIds = sections.map { it.exercise.id }.toSet()
    setHistories
        .filter { it.exerciseId != null && it.id !in consumedSetIds && it.exerciseId !in knownExerciseIds }
        .groupBy { it.exerciseId!! }
        .forEach { (exerciseId, histories) ->
            val exercise = findExerciseById(workout, exerciseId) ?: return@forEach
            sections += ExerciseSessionExportSection(
                label = exercise.name,
                exercise = exercise,
                setHistories = histories.sortedBy { it.order },
                rests = restHistories.filter { it.exerciseId == exercise.id }
            )
        }

    return sections
}

private fun appendCompactExerciseSessionMarkdown(
    markdown: StringBuilder,
    section: ExerciseSessionExportSection,
    history: WorkoutHistory,
    progressionByExerciseId: Map<UUID, ExerciseSessionProgression>,
    workoutStore: WorkoutStore,
    userAge: Int,
) {
    val timelineSets = section.setHistories.sortedBy { it.startTime ?: history.startTime }
    val activeSets = timelineSets.filterForInsightComparisonSets()
    if (timelineSets.isEmpty()) return

    val equipment = resolveSessionEquipment(section.exercise, timelineSets, workoutStore)
    val achievableWeights = equipment?.getWeightsCombinations()?.sorted()
    val progression = progressionByExerciseId[section.exercise.id]
    val expectedSets = progression?.expectedSets.orEmpty()
    val expectedWarmupTokens = compactExpectedWarmups(section.exercise, workoutStore, equipment)
        ?.takeUnless { it.startsWith("enabled") }
        ?.split(", ")
        .orEmpty()
    val timeline = mergeSessionTimeline(timelineSets, section.rests)
    val expectedWorkByIndex = expectedSets
        .mapIndexed { index, set ->
            index + 1 to formatExpectedSetForExecution(section.exercise, set, equipment, workoutStore)
        }
        .toMap()
    val plannedDurationSecondsByOrder = plannedDurationSecondsByOrderForExercise(section.exercise)
    val isUnilateralExecution = section.exercise.intraSetRestInSeconds?.let { it > 0 } == true &&
        timeline.anyIndexed { index, item ->
            if (item !is SessionTimelineItem.RestStep) return@anyIndexed false
            if (!item.history.isUnilateralSideRest(section.exercise.intraSetRestInSeconds)) return@anyIndexed false
            val previousSet = timeline.getOrNull(index - 1) as? SessionTimelineItem.SetStep
            val nextSet = timeline.getOrNull(index + 1) as? SessionTimelineItem.SetStep
            previousSet?.history?.isProgressionComparableWorkSet() == true &&
                nextSet?.history?.isProgressionComparableWorkSet() == true &&
                previousSet.history.order == nextSet.history.order
        }
    val unilateralOrders = if (isUnilateralExecution) {
        timelineSets
            .filter { it.isProgressionComparableWorkSet() }
            .groupingBy { it.order }
            .eachCount()
            .filterValues { count -> count > 1 }
            .keys
    } else {
        emptySet()
    }
    val workIndexByOrder = mutableMapOf<UInt, Int>()
    var nextWorkIndex = 1
    var warmupCounter = 1
    var calibrationCounter = 1
    var restPauseCounter = 1
    val unilateralSideCounters = mutableMapOf<UInt, Int>()
    val emittedUnilateralHeaders = mutableSetOf<UInt>()

    fun ensureWorkIndex(order: UInt): Int = workIndexByOrder.getOrPut(order) { nextWorkIndex++ }

    fun ensureUnilateralHeader(order: UInt) {
        if (emittedUnilateralHeaders.contains(order)) return
        emittedUnilateralHeaders += order
        val workIndex = ensureWorkIndex(order)
        val expected = expectedWorkByIndex[workIndex]
            ?: plannedDurationSecondsByOrder[order]?.let { formatDurationForExport(it) }
        val header = if (expected != null) {
            "Set $workIndex: expected: $expected"
        } else {
            "Set $workIndex:"
        }
        markdown.append("    - $header\n")
    }

    markdown.append("- ${section.label}\n")
    compactExerciseEquipmentLabel(section, equipment, workoutStore)?.let { label ->
        markdown.append("  - Equipment: $label\n")
    }
    compactExerciseRepRangeLine(section.exercise)?.let { line ->
        markdown.append("  - $line\n")
    }
    if (section.exercise.exerciseType == ExerciseType.BODY_WEIGHT &&
        section.exercise.bodyWeightPercentage != null
    ) {
        val relativeBodyWeight = workoutStore.weightKg * (section.exercise.bodyWeightPercentage / 100.0)
        markdown.append(
            "  - Baseline load: ${formatNumber(relativeBodyWeight)} kg " +
                "(${formatNumber(section.exercise.bodyWeightPercentage)}% of ${formatNumber(workoutStore.weightKg)} kg profile)\n"
        )
    }
    markdown.append("  - Execution:\n")
    timeline.forEachIndexed { index, item ->
        when (item) {
            is SessionTimelineItem.SetStep -> {
                val setHistory = item.history
                val setText = setHistory.toCompactSetToken(achievableWeights, equipment) ?: return@forEachIndexed
                val subCategory = setHistory.setSubCategory()
                when {
                    subCategory == SetSubCategory.WarmupSet -> {
                        val warmupIndex = warmupCounter++
                        val expected = expectedWarmupTokens.getOrNull(warmupIndex - 1)
                        val durationSuffix = setHistory.executionDurationSuffix()
                        val line = if (expected != null) {
                            "Warm-up $warmupIndex: expected: $expected | achieved: $setText$durationSuffix"
                        } else {
                            "Warm-up $warmupIndex: $setText$durationSuffix"
                        }
                        markdown.append("    - $line\n")
                    }
                    subCategory == SetSubCategory.CalibrationSet -> {
                        markdown.append(
                            "    - Calibration ${calibrationCounter++}: " +
                                "$setText${setHistory.executionDurationSuffix()}\n"
                        )
                    }
                    subCategory == SetSubCategory.CalibrationPendingSet -> {
                        markdown.append(
                            "    - Calibration (pending) ${calibrationCounter++}: " +
                                "$setText${setHistory.executionDurationSuffix()}\n"
                        )
                    }
                    subCategory == SetSubCategory.RestPauseSet -> {
                        markdown.append(
                            "    - Rest-pause ${restPauseCounter++}: " +
                                "$setText${setHistory.executionDurationSuffix()}\n"
                        )
                    }
                    setHistory.isProgressionComparableWorkSet() -> {
                        val order = setHistory.order
                        if (order in unilateralOrders) {
                            ensureUnilateralHeader(order)
                            val sideNumber = (unilateralSideCounters[order] ?: 0) + 1
                            unilateralSideCounters[order] = sideNumber
                            val sideLabel = when (sideNumber) {
                                1 -> "Side A"
                                2 -> "Side B"
                                else -> "Side $sideNumber"
                            }
                            markdown.append("      - $sideLabel: $setText${setHistory.executionDurationSuffix()}\n")
                        } else {
                            val workIndex = ensureWorkIndex(order)
                            val plannedDurationText = plannedDurationSecondsByOrder[order]
                                ?.let { formatDurationForExport(it) }
                            val expected = expectedWorkByIndex[workIndex] ?: plannedDurationText
                            val durationSuffix = setHistory.executionDurationSuffix()
                            val line = if (expected != null) {
                                "Set $workIndex: expected: $expected | achieved: $setText$durationSuffix"
                            } else {
                                "Set $workIndex: $setText$durationSuffix"
                            }
                            markdown.append("    - $line\n")
                        }
                    }
                    else -> {
                        markdown.append("    - Set: $setText${setHistory.executionDurationSuffix()}\n")
                    }
                }
            }
            is SessionTimelineItem.RestStep -> {
                val restText = item.history.toRestExportEntry()?.toCompactRestText() ?: return@forEachIndexed
                if (item.history.isUnilateralSideRest(section.exercise.intraSetRestInSeconds)) {
                    val previousSet = timeline.getOrNull(index - 1) as? SessionTimelineItem.SetStep
                    val nextSet = timeline.getOrNull(index + 1) as? SessionTimelineItem.SetStep
                    val unilateralOrder = previousSet?.history?.order ?: nextSet?.history?.order
                    if (unilateralOrder != null && unilateralOrder in unilateralOrders) {
                        ensureUnilateralHeader(unilateralOrder)
                        val sidesLogged = unilateralSideCounters[unilateralOrder] ?: 0
                        val label = if (sidesLogged == 0) "Before Side A" else "Intra-set rest"
                        markdown.append("      - $label: $restText\n")
                        return@forEachIndexed
                    }
                    markdown.append("    - Intra-set rest: $restText\n")
                } else {
                    markdown.append("    - Rest: $restText\n")
                }
            }
        }
    }
    if (expectedWarmupTokens.size >= warmupCounter) {
        val missing = buildList {
            for (index in warmupCounter..expectedWarmupTokens.size) {
                add(expectedWarmupTokens[index - 1])
            }
        }
        if (missing.isNotEmpty()) {
            markdown.append(
                "    - Planned warm-ups not logged: ${missing.joinToString("; ")}\n"
            )
        }
    }
    progression?.let {
        val summary = describeExpectedOutcome(it, activeSets, achievableWeights).substringBefore(" (")
        markdown.append("  - Summary: $summary\n")
    }
    compactExerciseHeartRateLine(
        history = history,
        setHistories = timelineSets.filter { !it.skipped },
        rests = section.rests,
        exercise = section.exercise,
        workoutStore = workoutStore,
        userAge = userAge
    )?.let { hrLine ->
        markdown.append("  - Heart rate: $hrLine\n")
    }
    progression?.let {
        markdown.append("  - Progression: ${it.progressionState.name}\n")
    }
}

private fun compactExerciseRepRangeLine(exercise: Exercise): String? {
    val low = minOf(exercise.minReps, exercise.maxReps)
    val high = maxOf(exercise.minReps, exercise.maxReps)
    if (high <= 0) return null
    return if (low == high) {
        "Rep range: $high reps"
    } else {
        "Rep range: $low-$high reps"
    }
}

private fun compactExerciseEquipmentLabel(
    section: ExerciseSessionExportSection,
    equipment: WeightLoadedEquipment?,
    workoutStore: WorkoutStore,
): String? {
    equipment?.let { return "${it.name} (${it.type})" }
    val snapshotName = section.setHistories
        .firstNotNullOfOrNull { history -> history.equipmentNameSnapshot?.takeIf { it.isNotBlank() } }
    val snapshotType = section.setHistories
        .firstNotNullOfOrNull { history -> history.equipmentTypeSnapshot?.takeIf { it.isNotBlank() } }
    if (snapshotName != null) {
        return if (snapshotType != null) "$snapshotName ($snapshotType)" else snapshotName
    }
    return section.exercise.equipmentId
        ?.let { id -> workoutStore.equipments.find { it.id == id } }
        ?.let { "${it.name} (${it.type})" }
}

private fun formatExpectedSets(
    expectedSets: List<SimpleSet>,
    equipment: WeightLoadedEquipment?,
): String {
    if (expectedSets.isEmpty()) return "not recorded"
    return expectedSets.joinToString(", ") {
        formatWeightWithRepsForExport(it.weight, it.reps, equipment)
    }
}

private fun compactExpectedWarmups(
    exercise: Exercise,
    workoutStore: WorkoutStore,
    equipment: WeightLoadedEquipment?,
): String? {
    val configuredWarmups = exercise.sets
        .filterNot { it is RestSet }
        .filter { set ->
            when (set) {
                is WeightSet -> set.subCategory == SetSubCategory.WarmupSet
                is com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet -> {
                    set.subCategory == SetSubCategory.WarmupSet
                }
                else -> false
            }
        }
        .map { formatSetInlineForExport(it, equipment) }
    if (configuredWarmups.isNotEmpty()) {
        return configuredWarmups.joinToString(", ")
    }

    if (!exercise.generateWarmUpSets) return null
    val resolvedEquipment = equipment ?: exercise.equipmentId?.let { id ->
        workoutStore.equipments.find { it.id == id }
    }
    if (resolvedEquipment == null) {
        return "enabled (equipment unavailable)"
    }
    val firstWorkSet = exercise.sets.firstOrNull { it is WeightSet && it.subCategory != SetSubCategory.WarmupSet }
    if (firstWorkSet !is WeightSet) {
        return "enabled"
    }

    val additionalWorkWeights = exercise.sets
        .filterIsInstance<WeightSet>()
        .filter { it.subCategory != SetSubCategory.WarmupSet }
        .drop(1)
        .map { it.weight }
        .filter { it > 0.0 }
    val availableTotals = resolvedEquipment.getWeightsCombinationsNoExtra()
    val warmups = if (resolvedEquipment is Barbell) {
        WarmupPlanner.buildWarmupSetsForBarbell(
            availableTotals = availableTotals,
            workWeight = firstWorkSet.weight,
            workReps = firstWorkSet.reps,
            barbell = resolvedEquipment,
            exercise = exercise,
            priorExercises = emptyList(),
            initialSetup = emptyList(),
            maxWarmups = 3,
            additionalWorkWeights = additionalWorkWeights
        )
    } else {
        WarmupPlanner.buildWarmupSets(
            availableTotals = availableTotals,
            workWeight = firstWorkSet.weight,
            workReps = firstWorkSet.reps,
            exercise = exercise,
            priorExercises = emptyList(),
            equipment = resolvedEquipment,
            maxWarmups = 3
        )
    }

    return warmups
        .takeIf { it.isNotEmpty() }
        ?.joinToString(", ") { (weight, reps) -> formatWeightWithRepsForExport(weight, reps, resolvedEquipment) }
        ?: "enabled"
}

private fun describeExpectedOutcome(
    progression: ExerciseSessionProgression?,
    activeSets: List<SetHistory>,
    achievableWeights: List<Double>?,
): String {
    if (progression == null || progression.expectedSets.isEmpty()) return "not available"
    val achieved = activeSets.toSimpleSets(achievableWeights)
    if (achieved.isEmpty()) return "below expected"

    val achievedTop = achieved.maxWithOrNull(compareBy<SimpleSet>({ it.weight }, { it.reps }))
    val expectedTop = progression.expectedSets.maxWithOrNull(compareBy<SimpleSet>({ it.weight }, { it.reps }))
    val achievedReps = achieved.sumOf { it.reps }
    val expectedReps = progression.expectedSets.sumOf { it.reps }

    val comparison = when {
        achievedTop != null && expectedTop != null && achievedTop.weight > expectedTop.weight -> "above expected"
        achievedTop != null && expectedTop != null && achievedTop.weight < expectedTop.weight -> "below expected"
        achievedReps > expectedReps -> "above expected"
        achievedReps < expectedReps -> "below expected"
        else -> "matched expected"
    }
    return "$comparison (${progression.vsExpected.name.lowercase()})"
}

private fun List<SetHistory>.toSimpleSets(
    achievableWeights: List<Double>?,
): List<SimpleSet> = mapNotNull { setHistory ->
    when (val setData = setHistory.setData) {
        is WeightSetData -> {
            val adjustedWeight = normalizeWeightForExport(setData.actualWeight, achievableWeights)
            SimpleSet(adjustedWeight, setData.actualReps)
        }
        is BodyWeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
        else -> null
    }
}

private fun List<SetHistory>.toCompactSetTokens(
    achievableWeights: List<Double>?,
    equipment: WeightLoadedEquipment?,
): List<String> = mapNotNull { setHistory ->
    if (setHistory.skipped) return@mapNotNull null
    when (val setData = setHistory.setData) {
        is WeightSetData -> {
            val adjustedWeight = normalizeWeightForExport(setData.actualWeight, achievableWeights)
            formatWeightWithRepsForExport(adjustedWeight, setData.actualReps, equipment)
        }
        is BodyWeightSetData -> formatWeightWithRepsForExport(setData.getWeight(), setData.actualReps, null)
        is TimedDurationSetData -> formatDurationForExport(extractActualDurationSeconds(setData))
        is EnduranceSetData -> formatDurationForExport(extractActualDurationSeconds(setData))
        else -> null
    }
}

private fun compactAchievedSets(
    section: ExerciseSessionExportSection,
    activeSets: List<SetHistory>,
    achievableWeights: List<Double>?,
    equipment: WeightLoadedEquipment?,
): List<String> {
    if ((section.exercise.intraSetRestInSeconds ?: 0) <= 0) {
        return activeSets.toCompactSetTokens(achievableWeights, equipment)
    }

    val setCountsByOrder = activeSets.groupingBy { it.order }.eachCount()
    val setNumbersByOrder = activeSets
        .map { it.order }
        .distinct()
        .withIndex()
        .associate { (index, order) -> order to index + 1 }
    val sideCountersByOrder = mutableMapOf<UInt, Int>()
    val timeline = mergeSessionTimeline(activeSets, section.rests)
    return timeline
        .mapIndexedNotNull { index, item ->
            when (item) {
                is SessionTimelineItem.SetStep -> {
                    if (item.history.skipped) return@mapIndexedNotNull null
                    val setNumber = setNumbersByOrder[item.history.order] ?: 1
                    val setText = item.history.toCompactSetToken(achievableWeights, equipment)
                        ?: return@mapIndexedNotNull null
                    if ((setCountsByOrder[item.history.order] ?: 0) > 1) {
                        val sideNumber = (sideCountersByOrder[item.history.order] ?: 0) + 1
                        sideCountersByOrder[item.history.order] = sideNumber
                        val sideLabel = when (sideNumber) {
                            1 -> "side A"
                            2 -> "side B"
                            else -> "side $sideNumber"
                        }
                        "set $setNumber $sideLabel: $setText"
                    } else {
                        "set $setNumber: $setText"
                    }
                }
                is SessionTimelineItem.RestStep -> {
                    if (!item.history.isUnilateralSideRest(section.exercise.intraSetRestInSeconds)) {
                        return@mapIndexedNotNull null
                    }
                    val previousSet = timeline.getOrNull(index - 1) as? SessionTimelineItem.SetStep
                    val nextSet = timeline.getOrNull(index + 1) as? SessionTimelineItem.SetStep
                    if (previousSet?.history?.order != nextSet?.history?.order) {
                        return@mapIndexedNotNull null
                    }
                    val restText = item.history.toRestExportEntry()?.toCompactRestText()
                        ?: return@mapIndexedNotNull null
                    "intra-set rest: $restText"
                }
            }
        }
}

private fun RestHistory.isUnilateralSideRest(intraSetRestSeconds: Int?): Boolean {
    val expectedSeconds = intraSetRestSeconds?.takeIf { it > 0 } ?: return false
    val plannedSeconds = (setData as? RestSetData)
        ?.startTimer
        ?.let(::normalizeTimerValueToSeconds)
    return plannedSeconds == expectedSeconds
}

private fun SetHistory.toCompactSetToken(
    achievableWeights: List<Double>?,
    equipment: WeightLoadedEquipment?,
): String? {
    if (skipped) return null
    return when (val setData = setData) {
        is WeightSetData -> {
            val adjustedWeight = normalizeWeightForExport(setData.actualWeight, achievableWeights)
            formatWeightWithRepsForExport(adjustedWeight, setData.actualReps, equipment)
        }
        is BodyWeightSetData -> formatBodyWeightSetForExecution(setData)
        is TimedDurationSetData -> formatDurationForExport(extractActualDurationSeconds(setData))
        is EnduranceSetData -> formatDurationForExport(extractActualDurationSeconds(setData))
        else -> null
    }
}

private fun formatExpectedSetForExecution(
    exercise: Exercise,
    set: SimpleSet,
    equipment: WeightLoadedEquipment?,
    workoutStore: WorkoutStore,
): String {
    if (exercise.exerciseType != ExerciseType.BODY_WEIGHT || exercise.bodyWeightPercentage == null) {
        return formatWeightWithRepsForExport(set.weight, set.reps, equipment)
    }
    val relativeBodyWeight = workoutStore.weightKg * (exercise.bodyWeightPercentage / 100.0)
    val additionalWeight = set.weight - relativeBodyWeight
    return formatRelativeBodyWeightSet(
        totalWeight = set.weight,
        relativeBodyWeight = relativeBodyWeight,
        reps = set.reps
    )
}

private fun formatBodyWeightSetForExecution(setData: BodyWeightSetData): String {
    return formatRelativeBodyWeightSet(
        totalWeight = setData.getWeight(),
        relativeBodyWeight = setData.relativeBodyWeightInKg,
        reps = setData.actualReps
    )
}

private fun formatRelativeBodyWeightSet(
    totalWeight: Double,
    relativeBodyWeight: Double,
    reps: Int,
): String {
    val additionalWeight = totalWeight - relativeBodyWeight
    return when {
        additionalWeight > 0.0001 -> {
            "Additional +${formatNumber(additionalWeight)} kg vs baseline, total ${formatNumber(totalWeight)} kg, $reps reps"
        }
        additionalWeight < -0.0001 -> {
            "Below baseline by ${formatNumber(abs(additionalWeight))} kg, total ${formatNumber(totalWeight)} kg, $reps reps"
        }
        else -> {
            "At baseline, total ${formatNumber(totalWeight)} kg, $reps reps"
        }
    }
}

private fun SetHistory.isWarmupSetHistory(): Boolean {
    return when (val setData = this.setData) {
        is WeightSetData -> setData.subCategory == SetSubCategory.WarmupSet
        is BodyWeightSetData -> setData.subCategory == SetSubCategory.WarmupSet
        else -> false
    }
}

private fun SetHistory.setSubCategory(): SetSubCategory? = when (val setData = this.setData) {
    is WeightSetData -> setData.subCategory
    is BodyWeightSetData -> setData.subCategory
    else -> null
}

private fun SetHistory.isProgressionComparableWorkSet(): Boolean {
    if (skipped) return false
    val subCategory = setSubCategory()
    if (subCategory == SetSubCategory.WarmupSet ||
        subCategory == SetSubCategory.CalibrationSet ||
        subCategory == SetSubCategory.CalibrationPendingSet ||
        subCategory == SetSubCategory.RestPauseSet
    ) {
        return false
    }
    return when (setData) {
        is WeightSetData,
        is BodyWeightSetData,
        is TimedDurationSetData,
        is EnduranceSetData,
        -> true
        else -> false
    }
}

private fun SetHistory.executionDurationSuffix(): String {
    val seconds = when (setData) {
        is TimedDurationSetData,
        is EnduranceSetData,
        -> return ""
        else -> {
            val start = startTime ?: return ""
            val end = endTime ?: return ""
            java.time.Duration.between(start, end).seconds.toInt().coerceAtLeast(0)
        }
    }
    if (seconds <= 0) return ""
    return " (elapsed ${formatDurationForExport(seconds)})"
}

private inline fun <T> List<T>.anyIndexed(predicate: (index: Int, item: T) -> Boolean): Boolean {
    for (index in indices) {
        if (predicate(index, this[index])) return true
    }
    return false
}

private fun compactSessionHeartRateLine(
    history: WorkoutHistory,
    workoutStore: WorkoutStore,
    userAge: Int,
): String? {
    val valid = history.heartBeatRecords.filter { it > 0 }
    if (valid.isEmpty()) return null
    val avg = valid.average().roundToInt()
    val peak = valid.maxOrNull() ?: return null
    val zones = compactZoneTime(valid, workoutStore, userAge)
    return buildString {
        append("avg $avg bpm, peak $peak bpm")
        if (zones.isNotBlank()) {
            append(", zones $zones")
        }
    }
}

private fun compactExerciseHeartRateLine(
    history: WorkoutHistory,
    setHistories: List<SetHistory>,
    rests: List<RestHistory>,
    exercise: Exercise,
    workoutStore: WorkoutStore,
    userAge: Int,
): String? {
    val samples = buildList {
        setHistories.forEach { setHistory ->
            addAll(sliceHeartRateRecords(history.startTime, history.heartBeatRecords, setHistory.startTime, setHistory.endTime))
        }
        rests.forEach { rest ->
            addAll(sliceHeartRateRecords(history.startTime, history.heartBeatRecords, rest.startTime, rest.endTime))
        }
    }.filter { it > 0 }
    if (samples.isEmpty()) return null
    val avg = samples.average().roundToInt()
    val peak = samples.maxOrNull() ?: return null
    val target = exerciseTargetZonePercent(samples, exercise, workoutStore, userAge)
    val targetRange = exerciseTargetZoneRange(exercise, workoutStore, userAge)
    return buildString {
        append("avg $avg bpm, peak $peak bpm")
        targetRange?.let { (low, high) -> append(", target range $low-$high bpm") }
        target?.let { append(", in range $it%") }
    }
}

private fun compactZoneTime(
    samples: List<Int>,
    workoutStore: WorkoutStore,
    userAge: Int,
): String {
    val bounds = heartRateZoneBoundsBpm(userAge, workoutStore.measuredMaxHeartRate, workoutStore.restingHeartRate)
    if (bounds.isEmpty()) return ""
    val counts = IntArray(bounds.size)
    samples.forEach { sample ->
        counts[zoneIndexForBpm(sample, bounds).coerceIn(0, bounds.lastIndex)] += 1
    }
    return counts.indices
        .mapNotNull { index -> counts[index].takeIf { it > 0 }?.let { "Z$index ${formatDurationForExport(it)}" } }
        .joinToString(" | ")
}

private fun compactSessionRestLine(rests: List<RestHistory>): String? {
    val entries = rests.mapNotNull { it.toRestExportEntry() }
    if (entries.isEmpty()) return null
    val planned = compactPlannedRestText(entries)
    val actual = compactActualRestText(entries)
    return when {
        planned != null && actual != null -> "$planned | $actual"
        planned != null -> planned
        else -> actual
    }
}

private fun exerciseTargetZonePercent(
    samples: List<Int>,
    exercise: Exercise,
    workoutStore: WorkoutStore,
    userAge: Int,
): Int? {
    val lowPct = exercise.lowerBoundMaxHRPercent ?: return null
    val highPct = exercise.upperBoundMaxHRPercent ?: return null
    val low = com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage(
        lowPct,
        userAge,
        workoutStore.measuredMaxHeartRate,
        workoutStore.restingHeartRate
    )
    val high = com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage(
        highPct,
        userAge,
        workoutStore.measuredMaxHeartRate,
        workoutStore.restingHeartRate
    )
    return (samples.count { it in low..high }.toDouble() / samples.size.toDouble() * 100.0).roundToInt()
}

private fun exerciseTargetZoneRange(
    exercise: Exercise,
    workoutStore: WorkoutStore,
    userAge: Int,
): Pair<Int, Int>? {
    val lowPct = exercise.lowerBoundMaxHRPercent ?: return null
    val highPct = exercise.upperBoundMaxHRPercent ?: return null
    val low = com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage(
        lowPct,
        userAge,
        workoutStore.measuredMaxHeartRate,
        workoutStore.restingHeartRate
    )
    val high = com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage(
        highPct,
        userAge,
        workoutStore.measuredMaxHeartRate,
        workoutStore.restingHeartRate
    )
    return minOf(low, high) to maxOf(low, high)
}

private fun compactRestSummary(rests: List<RestHistory>): String? {
    val entries = rests.mapNotNull { it.toRestExportEntry() }
    if (entries.isEmpty()) return null
    val planned = compactPlannedRestText(entries)
    val actual = compactActualRestText(entries)
    return when {
        planned != null && actual != null -> "$planned | $actual"
        planned != null -> planned
        else -> actual
    }
}

private fun RestHistory.toRestExportEntry(): RestExportEntry? {
    val planned = (setData as? RestSetData)
        ?.startTimer
        ?.let(::normalizeTimerValueToSeconds)
        ?.takeIf { it > 0 }
    val actual = startTime?.let { start ->
        endTime?.let { end ->
            java.time.Duration.between(start, end).seconds.toInt().takeIf { it > 0 }
        }
    }
    if (planned == null && actual == null) return null
    return RestExportEntry(plannedSeconds = planned, actualSeconds = actual)
}

private fun compactPlannedRestText(entries: List<RestExportEntry>): String? {
    val planned = entries.mapNotNull { it.plannedSeconds }
    if (planned.isEmpty()) return null
    val grouped = planned.groupingBy { it }.eachCount()
        .toSortedMap()
        .entries
        .joinToString(", ") { (seconds, count) ->
            val duration = formatDurationForExport(seconds)
            if (count == 1) duration else "${count}x$duration"
        }
    return "planned $grouped"
}

private fun RestExportEntry.toCompactRestText(): String? {
    return when {
        plannedSeconds != null && actualSeconds != null -> {
            "planned ${formatDurationForExport(plannedSeconds)} | actual ${formatDurationForExport(actualSeconds)}"
        }
        plannedSeconds != null -> "planned ${formatDurationForExport(plannedSeconds)}"
        actualSeconds != null -> "actual ${formatDurationForExport(actualSeconds)}"
        else -> null
    }
}

private fun compactActualRestText(entries: List<RestExportEntry>): String? {
    val actual = entries.mapNotNull { it.actualSeconds }
    if (actual.isEmpty()) return null
    val average = actual.average().roundToInt()
    return "actual ${actual.joinToString(", ") { formatDurationForExport(it) }} (avg ${formatDurationForExport(average)})"
}

private fun resolveSessionEquipment(
    exercise: Exercise,
    activeSetHistories: List<SetHistory>,
    workoutStore: WorkoutStore,
): WeightLoadedEquipment? {
    val historicalEquipmentId = activeSetHistories.firstOrNull()?.equipmentIdSnapshot ?: exercise.equipmentId
    return historicalEquipmentId?.let { id -> workoutStore.equipments.find { it.id == id } }
}

private fun findExerciseById(workout: Workout, exerciseId: UUID): Exercise? {
    workout.workoutComponents.forEach { component ->
        when (component) {
            is Exercise -> if (component.id == exerciseId) return component
            is Superset -> component.exercises.firstOrNull { it.id == exerciseId }?.let { return it }
            is Rest -> Unit
        }
    }
    return null
}

private fun compactAvailableLoads(equipment: WeightLoadedEquipment): String? {
    val weights = equipment.getWeightsCombinations().sorted()
    if (weights.isEmpty()) return null
    return weights.joinToString(", ") { w -> "${formatNumber(w)} kg" }
}

private fun plannedDurationSecondsByOrderForExercise(exercise: Exercise): Map<UInt, Int> {
    val result = mutableMapOf<UInt, Int>()
    exercise.sets.forEachIndexed { index, set ->
        val seconds = when (set) {
            is TimedDurationSet -> normalizeTimerValueToSeconds(set.timeInMillis)
            is EnduranceSet -> normalizeTimerValueToSeconds(set.timeInMillis)
            else -> 0
        }
        if (seconds > 0) {
            result[index.toUInt()] = seconds
        }
    }
    return result
}

private fun extractActualDurationSeconds(setData: TimedDurationSetData): Int {
    val startSeconds = normalizeTimerValueToSeconds(setData.startTimer)
    val endSeconds = normalizeTimerValueToSeconds(setData.endTimer)
    return when {
        startSeconds <= 0 -> 0
        endSeconds in 1 until startSeconds -> startSeconds - endSeconds
        setData.hasBeenExecuted && endSeconds <= 0 -> startSeconds
        setData.hasBeenExecuted && endSeconds == startSeconds -> startSeconds
        endSeconds > startSeconds -> endSeconds
        else -> 0
    }
}

private fun extractActualDurationSeconds(setData: EnduranceSetData): Int {
    val elapsedSeconds = normalizeTimerValueToSeconds(setData.endTimer)
    val fallbackSeconds = normalizeTimerValueToSeconds(setData.startTimer)
    return when {
        elapsedSeconds > 0 -> elapsedSeconds
        setData.hasBeenExecuted && fallbackSeconds > 0 -> fallbackSeconds
        else -> 0
    }
}

private fun normalizeTimerValueToSeconds(rawValue: Int): Int = when {
    rawValue <= 0 -> 0
    rawValue >= 1_000 -> rawValue / 1_000
    else -> rawValue
}

private fun startOfWeek(date: LocalDate): LocalDate {
    return date.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
}

private fun endOfWeek(date: LocalDate): LocalDate {
    return date.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY))
}

private suspend fun buildCompletedSessionsMarkdown(
    histories: List<WorkoutHistory>,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workoutStore: WorkoutStore,
    rangeStartDate: LocalDate?,
    rangeEndDate: LocalDate?,
): String {
    val markdown = StringBuilder()
    appendCompletedSessionsMarkdown(
        appendMarkdown = { markdown.append(it) },
        histories = histories,
        workoutHistoryDao = workoutHistoryDao,
        setHistoryDao = setHistoryDao,
        restHistoryDao = restHistoryDao,
        exerciseSessionProgressionDao = exerciseSessionProgressionDao,
        workoutStore = workoutStore,
        rangeStartDate = rangeStartDate,
        rangeEndDate = rangeEndDate
    )
    return markdown.toString()
}

private suspend fun appendCompletedSessionsMarkdown(
    appendMarkdown: suspend (String) -> Unit,
    histories: List<WorkoutHistory>,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workoutStore: WorkoutStore,
    rangeStartDate: LocalDate?,
    rangeEndDate: LocalDate?,
) {
    appendMarkdown("## Completed Sessions\n\n")
    if (histories.isEmpty()) {
        appendMarkdown("No completed workout sessions found.\n\n")
        return
    }

    val skippedSessions = mutableListOf<String>()
    histories.chunked(EXPORT_RENDER_BATCH_SIZE).forEachIndexed { batchIndex, batch ->
        val startIndex = batchIndex * EXPORT_RENDER_BATCH_SIZE
        val renderedSessions = coroutineScope {
            batch.mapIndexed { indexInBatch, history ->
                val index = startIndex + indexInBatch
                async {
                    renderSessionExportBlock(
                        index = index,
                        history = history,
                        workoutHistoryDao = workoutHistoryDao,
                        setHistoryDao = setHistoryDao,
                        restHistoryDao = restHistoryDao,
                        exerciseSessionProgressionDao = exerciseSessionProgressionDao,
                        workoutStore = workoutStore,
                        rangeStartDate = rangeStartDate,
                        rangeEndDate = rangeEndDate
                    )
                }
            }.awaitAll()
        }
        renderedSessions.sortedBy { it.index }.forEach { block ->
            if (block.markdown != null) {
                appendMarkdown("### Session ${block.index + 1}: ${block.history.date} ${block.history.time}\n\n")
                appendMarkdown(block.markdown.trim())
                appendMarkdown("\n\n")
            } else {
                skippedSessions += "${block.history.date} ${block.history.time}: ${block.failureMessage}"
            }
        }
    }
    appendSkippedItemsMarkdown(appendMarkdown, "Skipped sessions", skippedSessions)
}

private suspend fun renderSessionExportBlock(
    index: Int,
    history: WorkoutHistory,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workoutStore: WorkoutStore,
    rangeStartDate: LocalDate?,
    rangeEndDate: LocalDate?,
): SessionExportBlock {
    return try {
        when (
            val result = buildWorkoutSessionMarkdown(
                workoutHistoryId = history.id,
                workoutHistoryDao = workoutHistoryDao,
                setHistoryDao = setHistoryDao,
                restHistoryDao = restHistoryDao,
                exerciseSessionProgressionDao = exerciseSessionProgressionDao,
                workoutStore = workoutStore,
                historyStartDate = rangeStartDate,
                historyEndDate = rangeEndDate
            )
        ) {
            is WorkoutSessionMarkdownResult.Success -> SessionExportBlock(
                index = index,
                history = history,
                markdown = result.markdown,
                failureMessage = null
            )
            is WorkoutSessionMarkdownResult.Failure -> SessionExportBlock(
                index = index,
                history = history,
                markdown = null,
                failureMessage = result.message
            )
        }
    } catch (exception: CancellationException) {
        throw exception
    } catch (exception: Exception) {
        SessionExportBlock(
            index = index,
            history = history,
            markdown = null,
            failureMessage = exception.message ?: "Unexpected session export error"
        )
    }
}

private suspend fun buildExerciseHistorySummariesMarkdown(
    exercises: List<Exercise>,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workoutStore: WorkoutStore,
    rangeStartDate: LocalDate?,
    rangeEndDate: LocalDate?,
): String {
    val markdown = StringBuilder()
    appendExerciseHistorySummariesMarkdown(
        appendMarkdown = { markdown.append(it) },
        exercises = exercises,
        workoutHistoryDao = workoutHistoryDao,
        setHistoryDao = setHistoryDao,
        restHistoryDao = restHistoryDao,
        exerciseSessionProgressionDao = exerciseSessionProgressionDao,
        workoutStore = workoutStore,
        rangeStartDate = rangeStartDate,
        rangeEndDate = rangeEndDate
    )
    return markdown.toString()
}

private suspend fun appendExerciseHistorySummariesMarkdown(
    appendMarkdown: suspend (String) -> Unit,
    exercises: List<Exercise>,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workoutStore: WorkoutStore,
    rangeStartDate: LocalDate?,
    rangeEndDate: LocalDate?,
) {
    appendMarkdown("## Exercise History Summaries\n\n")
    val summaryScope = when {
        rangeStartDate != null && rangeEndDate != null -> {
            "exported completed sessions from $rangeStartDate to $rangeEndDate"
        }
        rangeStartDate != null -> "exported completed sessions since $rangeStartDate"
        rangeEndDate != null -> "exported completed sessions until $rangeEndDate"
        else -> "all completed sessions"
    }
    appendMarkdown(
        "These sections aggregate each exercise across $summaryScope. " +
            "For exact set and rest timing, prefer the completed-session timelines above.\n\n"
    )

    if (exercises.isEmpty()) {
        appendMarkdown("No exercises found in the current workout plan.\n\n")
        return
    }

    var exportedCount = 0
    val skippedExercises = mutableListOf<String>()
    exercises.chunked(EXPORT_RENDER_BATCH_SIZE).forEach { batch ->
        val renderedSummaries = coroutineScope {
            batch.map { exercise ->
                async {
                    renderExerciseSummaryExportBlock(
                        exercise = exercise,
                        workoutHistoryDao = workoutHistoryDao,
                        setHistoryDao = setHistoryDao,
                        restHistoryDao = restHistoryDao,
                        exerciseSessionProgressionDao = exerciseSessionProgressionDao,
                        workoutStore = workoutStore,
                        rangeStartDate = rangeStartDate,
                        rangeEndDate = rangeEndDate
                    )
                }
            }.awaitAll()
        }
        renderedSummaries.forEach { block ->
            if (block.markdown != null) {
                exportedCount += 1
                appendMarkdown("### Exercise Summary $exportedCount: ${block.exercise.name}\n\n")
                appendMarkdown(block.markdown.trim())
                appendMarkdown("\n\n")
            } else {
                skippedExercises += "${block.exercise.name}: ${block.failureMessage}"
            }
        }
    }
    if (exportedCount == 0) {
        appendMarkdown("No completed exercise histories with recorded sets found.\n\n")
    }
    appendSkippedItemsMarkdown(appendMarkdown, "Skipped exercise summaries", skippedExercises)
}

private suspend fun renderExerciseSummaryExportBlock(
    exercise: Exercise,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    restHistoryDao: RestHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workoutStore: WorkoutStore,
    rangeStartDate: LocalDate?,
    rangeEndDate: LocalDate?,
): ExerciseSummaryExportBlock {
    return try {
        when (
            val result = buildExerciseHistoryMarkdown(
                exercise = exercise,
                workoutHistoryDao = workoutHistoryDao,
                setHistoryDao = setHistoryDao,
                restHistoryDao = restHistoryDao,
                exerciseSessionProgressionDao = exerciseSessionProgressionDao,
                workouts = workoutStore.workouts,
                workoutStore = workoutStore,
                historyStartDate = rangeStartDate,
                historyEndDate = rangeEndDate
            )
        ) {
            is ExerciseHistoryMarkdownResult.Success -> ExerciseSummaryExportBlock(
                exercise = exercise,
                markdown = result.markdown,
                failureMessage = null
            )
            is ExerciseHistoryMarkdownResult.Failure -> ExerciseSummaryExportBlock(
                exercise = exercise,
                markdown = null,
                failureMessage = result.message
            )
        }
    } catch (exception: CancellationException) {
        throw exception
    } catch (exception: Exception) {
        ExerciseSummaryExportBlock(
            exercise = exercise,
            markdown = null,
            failureMessage = exception.message ?: "Unexpected exercise summary export error"
        )
    }
}

private suspend fun appendSkippedItemsMarkdown(
    appendMarkdown: suspend (String) -> Unit,
    heading: String,
    items: List<String>,
) {
    if (items.isEmpty()) return
    appendMarkdown("### $heading\n\n")
    items.forEach { item -> appendMarkdown("- $item\n") }
    appendMarkdown("\n")
}

private fun collectExercisesForExport(workoutStore: WorkoutStore): List<Exercise> {
    val exercisesById = linkedMapOf<UUID, Exercise>()
    workoutStore.workouts
        .sortedBy { it.order }
        .forEach { workout ->
            workout.workoutComponents.forEach { component ->
                when (component) {
                    is Exercise -> exercisesById.putIfAbsent(component.id, component)
                    is Superset -> component.exercises.forEach { exercise ->
                        exercisesById.putIfAbsent(exercise.id, exercise)
                    }
                    else -> Unit
                }
            }
        }
    return exercisesById.values.toList()
}
