package com.gabstra.myworkoutassistant.shared.motion

import com.google.gson.Gson
import com.google.gson.reflect.TypeToken

object MotionCaptureJson {
    private val gson = Gson()
    private val sensorConfigType = MotionCaptureSensorConfig::class.java
    private val labelType = MotionCaptureLabel::class.java
    private val candidateListType = object : TypeToken<List<MotionCaptureExerciseCandidate>>() {}.type
    private val stringListType = object : TypeToken<List<String>>() {}.type

    fun sensorConfigToJson(config: MotionCaptureSensorConfig): String = gson.toJson(config, sensorConfigType)

    fun sensorConfigFromJson(json: String): MotionCaptureSensorConfig =
        gson.fromJson(json, sensorConfigType) ?: MotionCaptureSensorConfig()

    fun labelToJson(label: MotionCaptureLabel): String = gson.toJson(label, labelType)

    fun labelFromJson(json: String): MotionCaptureLabel =
        gson.fromJson(json, labelType).let { label ->
            val noRepExpected = label.exerciseType?.supportsRepAnnotations()?.not() ?: label.noRepExpected
            label.copy(noRepExpected = noRepExpected)
        }

    fun candidateListToJson(candidates: List<MotionCaptureExerciseCandidate>): String =
        gson.toJson(candidates, candidateListType)

    fun candidateListFromJson(json: String): List<MotionCaptureExerciseCandidate> =
        (gson.fromJson<List<MotionCaptureExerciseCandidate>>(json, candidateListType) ?: emptyList()).map { candidate ->
            candidate.copy(noRepExpected = !candidate.exerciseType.supportsRepAnnotations())
        }

    fun stringListToJson(values: List<String>): String = gson.toJson(values, stringListType)

    fun stringListFromJson(json: String): List<String> =
        gson.fromJson(json, stringListType) ?: emptyList()
}
