package com.gabstra.myworkoutassistant.complications

import android.app.PendingIntent
import android.content.Intent
import androidx.wear.watchface.complications.data.ComplicationData
import androidx.wear.watchface.complications.data.ComplicationType
import androidx.wear.watchface.complications.data.LongTextComplicationData
import androidx.wear.watchface.complications.data.NoDataComplicationData
import androidx.wear.watchface.complications.data.PlainComplicationText
import androidx.wear.watchface.complications.data.ShortTextComplicationData
import androidx.wear.watchface.complications.datasource.ComplicationDataSourceService
import androidx.wear.watchface.complications.datasource.ComplicationRequest
import com.gabstra.myworkoutassistant.MainActivity

/**
 * Exposes the active workout timer as complication data, so any watch face slot can show the
 * countdown (the Now Bar cue itself is icon-only).
 */
class WorkoutTimerComplicationService : ComplicationDataSourceService() {

    override fun onComplicationRequest(
        request: ComplicationRequest,
        listener: ComplicationRequestListener,
    ) {
        val value = WorkoutComplication.currentValue(this)
        if (value == null) {
            listener.onComplicationData(NoDataComplicationData())
            return
        }
        listener.onComplicationData(
            buildData(request.complicationType, WorkoutComplication.currentLabel(this), value)
        )
    }

    override fun getPreviewData(type: ComplicationType): ComplicationData? =
        buildData(type, "Set", "12:34")

    private fun buildData(type: ComplicationType, label: String, value: String): ComplicationData {
        val text = PlainComplicationText.Builder(value).build()
        val contentDescription = PlainComplicationText.Builder("$label $value").build()
        val title = PlainComplicationText.Builder(label).build()
        val tapAction = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return when (type) {
            ComplicationType.LONG_TEXT ->
                LongTextComplicationData.Builder(text, contentDescription)
                    .setTitle(title)
                    .setTapAction(tapAction)
                    .build()

            else ->
                ShortTextComplicationData.Builder(text, contentDescription)
                    .setTitle(title)
                    .setTapAction(tapAction)
                    .build()
        }
    }
}
