package com.gabstra.myworkoutassistant

import android.content.Context
import androidx.annotation.StringRes
import com.gabstra.myworkoutassistant.shared.SetType
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureLabelKind
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureReviewStatus
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionStatus

/**
 * Localized display labels for app-owned enum values shown in mobile UI.
 *
 * Persisted free-form values (report state names and session statuses) keep their raw value when
 * they are not one of the known app-owned constants, so unknown data is never hidden.
 */

@StringRes
fun SetType.labelRes(): Int = when (this) {
    SetType.COUNTUP_SET -> R.string.loc_audit_set_type_countup
    SetType.BODY_WEIGHT_SET -> R.string.loc_audit_set_type_body_weight
    SetType.COUNTDOWN_SET -> R.string.loc_audit_set_type_countdown
    SetType.WEIGHT_SET -> R.string.loc_audit_set_type_weight
    SetType.RUNNING_SET -> R.string.loc_audit_set_type_running
}

@StringRes
fun EquipmentType.labelRes(): Int = when (this) {
    EquipmentType.GENERIC -> R.string.loc_audit_equipment_generic
    EquipmentType.BARBELL -> R.string.loc_audit_equipment_barbell
    EquipmentType.DUMBBELLS -> R.string.loc_audit_equipment_dumbbells
    EquipmentType.DUMBBELL -> R.string.loc_audit_equipment_dumbbell
    EquipmentType.PLATELOADEDCABLE -> R.string.loc_audit_equipment_plate_loaded_cable
    EquipmentType.WEIGHTVEST -> R.string.loc_audit_equipment_weight_vest
    EquipmentType.MACHINE -> R.string.loc_audit_equipment_machine
    EquipmentType.CARDIO_MACHINE -> R.string.loc_audit_equipment_cardio_machine
    EquipmentType.IRONNECK -> R.string.loc_audit_equipment_iron_neck
    EquipmentType.ACCESSORY -> R.string.loc_audit_equipment_accessory
}

fun EquipmentType.localizedLabel(context: Context): String = context.getString(labelRes())

@StringRes
fun MotionCaptureLabelKind.labelRes(): Int = when (this) {
    MotionCaptureLabelKind.EXERCISE -> R.string.loc_audit_sensor_kind_exercise
    MotionCaptureLabelKind.REST -> R.string.loc_audit_sensor_kind_rest
    MotionCaptureLabelKind.TRANSITION -> R.string.loc_audit_sensor_kind_transition
}

@StringRes
fun MotionCaptureReviewStatus.labelRes(): Int = when (this) {
    MotionCaptureReviewStatus.PENDING -> R.string.loc_audit_sensor_review_pending
    MotionCaptureReviewStatus.CONFIRMED -> R.string.loc_audit_sensor_review_confirmed
    MotionCaptureReviewStatus.RELABELED -> R.string.loc_audit_sensor_review_relabeled
    MotionCaptureReviewStatus.MARKED_REST -> R.string.loc_audit_sensor_review_marked_rest
    MotionCaptureReviewStatus.DROPPED -> R.string.loc_audit_sensor_review_dropped
}

@StringRes
fun MotionCaptureSessionStatus.labelRes(): Int = when (this) {
    MotionCaptureSessionStatus.ACTIVE -> R.string.loc_audit_sensor_status_active
    MotionCaptureSessionStatus.COMPLETED -> R.string.loc_audit_sensor_status_completed
    MotionCaptureSessionStatus.ABANDONED -> R.string.loc_audit_sensor_status_abandoned
}

/** Localizes a known session status; unknown persisted statuses are returned unchanged. */
fun localizedSessionStatus(context: Context, rawStatus: String): String {
    val knownStatus = MotionCaptureSessionStatus.entries.firstOrNull { it.name == rawStatus }
    return knownStatus?.let { context.getString(it.labelRes()) } ?: rawStatus
}

/** Localizes the app-owned report state names; any other persisted name is returned unchanged. */
fun localizedSensorStateName(context: Context, stateName: String): String = when (stateName) {
    "Set" -> context.getString(R.string.loc_audit_sensor_state_set)
    "Rest" -> context.getString(R.string.loc_audit_sensor_state_rest)
    else -> stateName
}
