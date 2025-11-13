package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.HapticsViewModel
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.shared.Green
import com.gabstra.myworkoutassistant.shared.Red
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.formatWeight
import com.gabstra.myworkoutassistant.shared.isEqualTo
import com.gabstra.myworkoutassistant.shared.round
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState

private fun Double.compact(): String {
    val s = String.format("%.2f", this).replace(',', '.')
    return s.trimEnd('0').trimEnd('.')
}

private fun buildPerSidePlatesLabel(plates: List<Double>): String {
    if (plates.isEmpty()) return "—"
    val counts = plates.groupingBy { it }.eachCount()
    // Keep descending order by weight
    return counts.keys.sorted().joinToString(" - ") { w ->
        val c = counts.getValue(w)
        val ws = w.compact()
        if (c == 1) ws else "${ws}x$c"
    }
}

@SuppressLint("DefaultLocale")
@Composable
fun PagePlates(updatedState: WorkoutState.Set, equipment: WeightLoadedEquipment?, hapticsViewModel: HapticsViewModel) {
    val scrollState = rememberScrollState()
    var headerMarqueeEnabled by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(5.dp)
    ) {
        Text(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp),
            text = "Loading Guide",
            style = MaterialTheme.typography.titleSmall,
            textAlign = TextAlign.Center
        )

        if (equipment == null || equipment !is Barbell || updatedState.plateChangeResult == null) {
            Text(
                text = "NOT AVAILABLE",
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center
            )
        } else {
            Row(
                modifier = Modifier.fillMaxWidth().padding(vertical = 5.dp),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                val previousSideWeightTotal = remember(updatedState.plateChangeResult!!.previousPlates) { updatedState.plateChangeResult!!.previousPlates.sum().round(2) }
                val currentSideWeightTotal = remember(updatedState.plateChangeResult!!.currentPlates) { updatedState.plateChangeResult!!.currentPlates.sum().round(2) }

                val previousWeightTotal = remember(equipment.barWeight,previousSideWeightTotal) { (equipment.barWeight + (previousSideWeightTotal*2)).round(2) }
                val currentWeightTotal = remember(equipment.barWeight,currentSideWeightTotal) { (equipment.barWeight + (currentSideWeightTotal*2)).round(2) }

                if (previousSideWeightTotal.isEqualTo(currentSideWeightTotal) || previousSideWeightTotal == 0.0) {
                    val topLine = buildAnnotatedString {
                        @Composable
                        fun pipe() {
                            withStyle(
                                SpanStyle(
                                    //color = MaterialTheme.colorScheme.surfaceContainerHigh,
                                    fontWeight = FontWeight.Bold
                                )
                            ) {
                                append(" • ")
                            }
                        }

                        append("Σ ${formatWeight(currentWeightTotal)}")
                        pipe()
                        append("Bar ${formatWeight(equipment.barWeight)}")
                    }

                    Text(
                        text = topLine,
                        style = MaterialTheme.typography.bodySmall,
                        textAlign = TextAlign.Center,
                        maxLines = 1,
                        modifier = Modifier.clickable {
                            headerMarqueeEnabled = !headerMarqueeEnabled
                            hapticsViewModel.doGentleVibration()
                        }
                        .then(if (headerMarqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier)
                    )
                }else {
                    val topLine = buildAnnotatedString {
                        @Composable
                        fun pipe() {
                            withStyle(
                                SpanStyle(
                                    //color = MaterialTheme.colorScheme.surfaceContainerHigh,
                                    fontWeight = FontWeight.Bold
                                )
                            ) {
                                append(" • ")
                            }
                        }

                        append("Σ ${formatWeight(previousWeightTotal)}")
                        append( " → ")
                        append("${formatWeight(currentWeightTotal)}")
                        pipe()
                        append("Bar ${formatWeight(equipment.barWeight)}")
                    }

                    Text(
                        text = topLine,
                        style = MaterialTheme.typography.bodySmall,
                        textAlign = TextAlign.Center,
                        maxLines = 1,
                        modifier = Modifier.clickable {
                            headerMarqueeEnabled = !headerMarqueeEnabled
                            hapticsViewModel.doGentleVibration()
                        }
                        .then(if (headerMarqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier)
                    )
                }
            }

            val headerStyle = MaterialTheme.typography.bodyExtraSmall
            var platesMarqueeEnabled by remember { mutableStateOf(false) }

            val perSideLabel = remember(updatedState.plateChangeResult!!.currentPlates) {
                buildPerSidePlatesLabel(updatedState.plateChangeResult!!.currentPlates)
            }

            if (updatedState.plateChangeResult!!.change.steps.isEmpty()) {
                Text(
                    text = "NO CHANGES REQUIRED",
                    modifier = Modifier.fillMaxWidth(),
                    style = MaterialTheme.typography.bodySmall,
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onBackground
                )
            } else {
                Column(
                    modifier = Modifier
                        .weight(1f),
                    verticalArrangement = Arrangement.spacedBy(2.5.dp),
                ) {
                    Text(
                        modifier = Modifier.fillMaxWidth(),
                        text = "PLATE CHANGES (per side)",
                        style = headerStyle,
                        textAlign = TextAlign.Center,
                        color = MaterialTheme.colorScheme.onBackground
                    )

                    val style = MaterialTheme.typography.numeralSmall

                    val prototypeItem = @Composable {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(30.dp)
                                .padding(horizontal = 10.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) { }
                    }

                    DynamicHeightColumn(
                        modifier = Modifier
                            .weight(1f) // Fills remaining vertical space
                            .fillMaxWidth(), // Still need to fill width
                        prototypeItem = { prototypeItem() }
                    ) {
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .verticalColumnScrollbar(
                                    scrollState = scrollState,
                                    scrollBarColor = MaterialTheme.colorScheme.onBackground,
                                    enableTopFade = false,
                                    enableBottomFade = false
                                )
                                .verticalScroll(scrollState),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            updatedState.plateChangeResult!!.change.steps.forEachIndexed { index, step ->
                                val color = if (step.action == PlateCalculator.Companion.Action.ADD) {
                                    Green
                                } else {
                                    Red
                                }

                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .padding(horizontal = 10.dp)
                                        .height(30.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    val weightText = String.format("%.2f", step.weight).replace(",", ".")

                                    val actionText =
                                        if (step.action == PlateCalculator.Companion.Action.ADD) {
                                            "+"
                                        } else {
                                            "-"
                                        }

                                    val shape = RoundedCornerShape(25)

                                    Row(
                                        modifier = Modifier
                                            .height(27.5.dp)
                                            .padding(bottom = 2.5.dp)
                                            .border(BorderStroke(1.dp, color), shape)
                                            .clip(shape), // keep if you want content clipped to the rounded shape
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        ScalableText(
                                            modifier = Modifier.fillMaxSize().padding(3.dp),
                                            text = "$actionText $weightText",
                                            style = style,
                                            textAlign = TextAlign.Center,
                                            color = color
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Column{
                Text(
                    modifier = Modifier.fillMaxWidth(),
                    text = "PLATES STACK",
                    style = headerStyle,
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onBackground
                )
                Spacer(modifier = Modifier.height(2.5.dp))
                Text(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 10.dp)
                        .clickable {
                            platesMarqueeEnabled = !platesMarqueeEnabled
                            hapticsViewModel.doGentleVibration()
                        }
                        .then(if (platesMarqueeEnabled) Modifier.basicMarquee(iterations = Int.MAX_VALUE) else Modifier),
                    text = perSideLabel,                       // e.g., "20 - 10 - 5x2 - 1.25 - 0.25"
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
                    textAlign = TextAlign.Center,
                    overflow = TextOverflow.Ellipsis,
                    maxLines = 1
                )
            }


        }
    }
}
