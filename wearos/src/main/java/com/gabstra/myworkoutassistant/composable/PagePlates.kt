package com.gabstra.myworkoutassistant.composable

import android.annotation.SuppressLint
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.utils.PlateCalculator
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutState

@SuppressLint("DefaultLocale")
@Composable
fun PagePlates(updatedState: WorkoutState.Set, equipment: WeightLoadedEquipment?) {
    val scrollState = rememberScrollState()
    Column(
        modifier = Modifier.fillMaxSize().padding(horizontal = 5.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            modifier = Modifier.fillMaxWidth(),
            text = "Plates",
            style = MaterialTheme.typography.title3,
            textAlign = TextAlign.Center
        )
        Spacer(modifier = Modifier.height(10.dp))

        if (equipment == null || equipment !is Barbell || updatedState.plateChangeResult == null) {
            Text(
                text = "NOT AVAILABLE",
                style = MaterialTheme.typography.body1,
                textAlign = TextAlign.Center
            )
        } else {
            if (updatedState.plateChangeResult!!.change.steps.isEmpty()) {
                Text(
                    text = "Keep current plates",
                    modifier = Modifier.fillMaxWidth(),
                    style = MaterialTheme.typography.body1,
                    textAlign = TextAlign.Center
                )
            } else {
                val typography = MaterialTheme.typography
                val headerStyle =
                    remember { typography.body1.copy(fontSize = typography.body1.fontSize * 0.625f) }

                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(horizontal = 10.dp)
                        .padding(bottom = 10.dp),
                    verticalArrangement = Arrangement.spacedBy(5.dp),
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 10.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            modifier = Modifier.weight(1f),
                            text = "#",
                            style = headerStyle,
                            textAlign = TextAlign.Center
                        )
                        Text(
                            modifier = Modifier.weight(2f),
                            text = "PLATES",
                            style = headerStyle,
                            textAlign = TextAlign.Center
                        )
                    }

                    if (updatedState.plateChangeResult!!.change.steps.isNotEmpty()) {
                        val style = MaterialTheme.typography.body1

                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .verticalColumnScrollbar(
                                    scrollState = scrollState,
                                    scrollBarColor = MyColors.White
                                )
                                .padding(horizontal = 10.dp)
                                .verticalScroll(scrollState),
                            verticalArrangement = Arrangement.spacedBy(3.dp),
                            horizontalAlignment = Alignment.CenterHorizontally
                        ) {
                            updatedState.plateChangeResult!!.change.steps.forEachIndexed { index, step ->
                                Row(
                                    modifier = Modifier.fillMaxWidth(),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Text(
                                        modifier = Modifier.weight(1f),
                                        text = "${index + 1}",
                                        style = MaterialTheme.typography.body1,
                                        textAlign = TextAlign.Center
                                    )
                                    val weightText = String.format("%.2f", step.weight).replace(",", ".")


                                    val actionText =
                                        if (step.action == PlateCalculator.Companion.Action.ADD) {
                                            "+"
                                        } else {
                                            "-"
                                        }

                                    Row(
                                        modifier = Modifier.weight(2f),
                                        horizontalArrangement = Arrangement.Center
                                    ) {
                                        Row(
                                            horizontalArrangement = Arrangement.spacedBy(5.dp)
                                        ){
                                            Text(
                                                text = actionText,
                                                style = style,
                                                textAlign = TextAlign.End,
                                            )
                                            Text(
                                                text = weightText,
                                                style = style,
                                                textAlign = TextAlign.Start,
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
}
