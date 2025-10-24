package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
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
import androidx.compose.ui.text.style.BaselineShift
import androidx.compose.ui.text.style.TextAlign
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
                text = "Not available",
                style = MaterialTheme.typography.labelSmall,
                textAlign = TextAlign.Center
            )
        } else {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically
            ) {
                val previousSideWeightTotal = remember(updatedState.plateChangeResult!!.previousPlates) { updatedState.plateChangeResult!!.previousPlates.sum().round(2) }
                val currentSideWeightTotal = remember(updatedState.plateChangeResult!!.currentPlates) { updatedState.plateChangeResult!!.currentPlates.sum().round(2) }

                val previousWeightTotal = remember(equipment.barWeight,previousSideWeightTotal) { (equipment.barWeight + (previousSideWeightTotal*2)).round(2) }
                val currentWeightTotal = remember(equipment.barWeight,currentSideWeightTotal) { (equipment.barWeight + (currentSideWeightTotal*2)).round(2) }

                if (previousSideWeightTotal.isEqualTo(currentSideWeightTotal) || previousSideWeightTotal == 0.0) {
                    val topLine = buildList {
                        add("Σ ${formatWeight(currentWeightTotal)}")
                        add("Bar ${formatWeight(equipment.barWeight)}")
                    }.joinToString(" • ")

                    Text(
                        text = topLine,
                        style = MaterialTheme.typography.labelSmall,
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
                        append("Σ ${formatWeight(previousWeightTotal)}")
                        withStyle(SpanStyle(baselineShift = BaselineShift(0.18f))) { // tweak 0.12–0.25f as needed
                            append( " → ")
                        }
                        append("${formatWeight(currentWeightTotal)}")
                        append(" • ")
                        append("Bar ${formatWeight(equipment.barWeight)}")
                    }

                    Text(
                        text = topLine,
                        style = MaterialTheme.typography.labelSmall,
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

            if (updatedState.plateChangeResult!!.change.steps.isEmpty()) {
                Text(
                    text = "No changes required",
                    modifier = Modifier.fillMaxWidth(),
                    style = MaterialTheme.typography.labelSmall,
                    textAlign = TextAlign.Center,
                    color = MaterialTheme.colorScheme.onBackground
                )
            } else {
                val headerStyle = MaterialTheme.typography.labelSmall

                Column(
                    modifier = Modifier
                        .weight(1f).padding(horizontal = 10.dp),
                    verticalArrangement = Arrangement.spacedBy(2.5.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 10.dp),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "PLATES (KG/SIDE)",
                            style = headerStyle,
                            textAlign = TextAlign.Center,
                            color = MaterialTheme.colorScheme.onBackground
                        )
                    }

                    val style = MaterialTheme.typography.numeralSmall

                    val prototypeItem = @Composable {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(25.dp)
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
                                        .height(25.dp),
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
                                            .height(22.5.dp)
                                            .padding(bottom = 2.5.dp)
                                            .border(BorderStroke(1.dp, color), shape)
                                            .clip(shape), // keep if you want content clipped to the rounded shape
                                        verticalAlignment = Alignment.CenterVertically
                                    ) {
                                        ScalableText(
                                            modifier = Modifier.fillMaxSize(),
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
        }
    }
}
