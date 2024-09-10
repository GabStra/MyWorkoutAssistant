package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Divider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.formatSecondsToMinutesSeconds
import com.gabstra.myworkoutassistant.formatTime
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData

@Composable
fun SetHistoriesRenderer(modifier: Modifier = Modifier, setHistories: List<SetHistory>) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.End,
        verticalArrangement = Arrangement.spacedBy(5.dp),
    ) {
        for (set in setHistories) {
            Row {
                when (val setData = set.setData) {
                    is WeightSetData -> {
                        Text(
                            text = "${setData.actualReps} @ ${setData.actualWeight} kg",
                            style = MaterialTheme.typography.bodyMedium,
                            color = Color.White.copy(alpha = .87f),
                        )
                    }

                    is BodyWeightSetData -> {
                        Text(
                            text = "x${setData.actualReps}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = Color.White.copy(alpha = .87f),
                        )
                    }

                    is TimedDurationSetData -> {
                        Column(
                            horizontalAlignment = Alignment.End,
                        ) {
                            Text(
                                "Timer set to: " + formatTime(setData.startTimer / 1000) + " (hh:mm:ss)",
                                style = MaterialTheme.typography.bodyMedium,
                                color = Color.White.copy(alpha = .87f)
                            )
                            Text(
                                "Stopped at: " + formatTime(setData.endTimer / 1000) + " (hh:mm:ss)",
                                style = MaterialTheme.typography.bodyMedium,
                                color = Color.White.copy(alpha = .87f)
                            )
                        }
                    }

                    is EnduranceSetData -> {
                        Column(
                            horizontalAlignment = Alignment.End,
                        ) {
                            Text("Timer set to: " + formatTime(setData.startTimer / 1000) + " (hh:mm:ss)",
                                style = MaterialTheme.typography.bodyMedium,
                                color = Color.White.copy(alpha = .6f)
                            )
                            Text("Stopped at: " + formatTime(setData.endTimer / 1000) + " (hh:mm:ss)",
                                style = MaterialTheme.typography.bodyMedium,
                                color = Color.White.copy(alpha = .6f)
                            )
                        }
                    }
                }
            }

        }
    }
}