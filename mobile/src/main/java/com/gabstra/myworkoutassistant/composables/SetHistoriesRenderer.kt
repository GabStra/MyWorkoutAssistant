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
    ) {
        for (set in setHistories) {
            Row {
                when (val setData = set.setData) {
                    is WeightSetData -> {
                        Text(
                            text = "x${setData.actualReps} @ ${setData.actualWeight} kg",
                            style = MaterialTheme.typography.bodyMedium,
                            color = Color.White.copy(alpha = .6f),
                        )
                    }

                    is BodyWeightSetData -> {
                        Text(
                            text = "x${setData.actualReps}",
                            style = MaterialTheme.typography.bodyMedium,
                            color = Color.White.copy(alpha = .6f),
                        )
                    }

                    is TimedDurationSetData -> {
                        Column{
                            Text(
                                "Timer set to: " + formatSecondsToMinutesSeconds(setData.startTimer / 1000) + " (mm:ss)",
                                style = MaterialTheme.typography.bodyMedium,
                                color = Color.White.copy(alpha = .6f)
                            )
                            Text(
                                "Stopped at: " + formatSecondsToMinutesSeconds(setData.endTimer / 1000) + " (mm:ss)",
                                style = MaterialTheme.typography.bodyMedium,
                                color = Color.White.copy(alpha = .6f)
                            )
                        }
                    }

                    is EnduranceSetData -> {
                        Column{
                            Text("Timer set to: " + formatSecondsToMinutesSeconds(setData.startTimer / 1000) + " (mm:ss)",
                                style = MaterialTheme.typography.bodyMedium,
                                color = Color.White.copy(alpha = .6f)
                            )
                            Text("Stopped at: " + formatSecondsToMinutesSeconds(setData.endTimer / 1000) + " (mm:ss)",
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