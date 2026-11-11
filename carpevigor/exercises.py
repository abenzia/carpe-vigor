"""The exercises a training week is built from: bodyweight or household objects, at home, no gym.

Each movement pattern is a ladder, from the easiest rung to the hardest. The program (training.py) picks a rung from
the person's level and moves it one step at a time with their own feedback ("too easy", "too hard", "it hurt").
Each exercise says what it asks of the body, so the person's limits can rule it out by plain code:
- floor: done lying or kneeling on the floor (getting down and up again is part of it);
- impact: feet leave the ground (jumping, jogging);
- knees / back / shoulders: loads that joint noticeably;
- hold: a static hold (plank), where people tend to hold their breath;
- balance: standing on a narrow or single-leg base.
The words are ours, written for people in general; how much to do comes from the program, never from here.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Exercise:
    id: str
    name: str
    how: tuple[str, ...]          # how to do it, step by step
    mistakes: tuple[str, ...]     # what to watch for
    floor: bool = False
    impact: bool = False
    knees: bool = False
    back: bool = False
    shoulders: bool = False
    hold: bool = False            # counted in seconds, not reps
    balance: bool = False
    clip: str = ""                # static/exercises/<clip>.mp4 (made with Veo); the exercise's own id unless shared
    areas: tuple[str, ...] = field(default=())   # coach.AREAS it works, for the 3D body


def E(id, name, how, mistakes, **kw) -> Exercise:
    return Exercise(id, name, tuple(how), tuple(mistakes), **{"clip": id, **kw})


# pattern: the ladder, easiest first
LADDERS: dict[str, list[Exercise]] = {
    "squat": [
        E("sit_to_stand", "Chair sit-to-stand",
          ["Sit near the front of a sturdy chair, feet hip-width apart.", "Lean slightly forward and stand up, pushing through your heels.",
           "Sit back down slowly, in control, without dropping."],
          ["Knees falling inward", "Using the hands to push off (use them only if you need to)"],
          clip="sit_to_stand", areas=("legs", "glutes")),
        E("box_squat", "Squat to a chair",
          ["Stand in front of a chair, feet shoulder-width apart, arms forward.", "Sit back as if to sit, touch the seat lightly.",
           "Stand up without resting on the chair."],
          ["Heels lifting", "Rounding the lower back at the bottom"], knees=True, areas=("legs", "glutes")),
        E("squat", "Bodyweight squat",
          ["Feet shoulder-width apart, toes slightly out.", "Push the hips back and bend the knees as low as is comfortable.",
           "Drive back up through the whole foot."],
          ["Knees caving in", "Chest dropping forward"], knees=True, areas=("legs", "glutes")),
        E("tempo_squat", "Slow squat (3 seconds down)",
          ["As the bodyweight squat, but count three seconds on the way down.", "Pause one second at the bottom, then stand up."],
          ["Rushing the way up", "Holding the breath: breathe out as you stand"], knees=True, areas=("legs", "glutes")),
    ],
    "hinge": [
        E("hip_hinge", "Standing hip hinge",
          ["Stand tall, hands on the front of your thighs, knees soft.", "Push the hips back, sliding the hands toward the knees, back flat.",
           "Squeeze the glutes to stand tall again."],
          ["Rounding the back", "Bending the knees into a squat"], areas=("glutes", "back")),
        E("glute_bridge", "Glute bridge",
          ["Lie on your back, knees bent, feet flat, arms by your sides.", "Press through the heels and lift the hips until knees, hips and shoulders line up.",
           "Lower slowly."],
          ["Arching the lower back at the top", "Pushing through the toes"], floor=True, areas=("glutes", "legs", "core")),
        E("backpack_hinge", "Hip hinge holding a backpack",
          ["Hold a lightly loaded backpack against your chest.", "Hinge as in the standing hip hinge, back flat.", "Stand tall by squeezing the glutes."],
          ["Letting the weight pull the back round", "Too much load: it should feel moderate"], back=True, areas=("glutes", "back", "legs")),
        E("single_bridge", "Single-leg glute bridge",
          ["As the glute bridge, with one foot lifted and that knee bent.", "Keep the hips level as you lift and lower."],
          ["Hips tilting to one side"], floor=True, areas=("glutes", "legs", "core")),
    ],
    "push": [
        E("wall_pushup", "Wall push-up",
          ["Hands on the wall at shoulder height, slightly wider than the shoulders.", "Step back until the body leans in a straight line.",
           "Bend the elbows to bring the chest toward the wall, then push away."],
          ["Hips sagging or sticking out", "Elbows flaring straight out to the sides"], areas=("chest", "arms", "shoulders")),
        E("counter_pushup", "Counter push-up",
          ["Hands on a kitchen counter or sturdy table edge.", "Body in a straight line from head to heels.", "Lower the chest to the edge and push back up."],
          ["Head dropping forward", "Sagging hips"], shoulders=True, areas=("chest", "arms", "shoulders")),
        E("knee_pushup", "Push-up on the knees",
          ["Kneel, hands on the floor under the shoulders.", "Keep a straight line from knees to head.", "Lower the chest toward the floor and press up."],
          ["Bottom sticking up", "Elbows wide"], floor=True, shoulders=True, areas=("chest", "arms", "shoulders")),
        E("pushup", "Push-up",
          ["Hands under the shoulders, legs straight, body like a plank.", "Lower the chest close to the floor, elbows at about 45 degrees.", "Press back up."],
          ["Sagging hips", "Half movements"], floor=True, shoulders=True, areas=("chest", "arms", "shoulders", "core")),
    ],
    "pull": [
        E("wall_w", "Wall W-slide",
          ["Stand with your back against a wall, arms bent in a W shape against it.", "Slide the arms up into a Y, keeping contact with the wall.",
           "Pull the elbows back down, squeezing the shoulder blades."],
          ["Arching the lower back off the wall", "Shrugging the shoulders"], areas=("back", "shoulders")),
        E("bottle_row", "Bent-over row with water bottles",
          ["Hold a full water bottle in each hand, hinge forward with a flat back.", "Pull the elbows back toward the hips.", "Lower slowly."],
          ["Rounding the back", "Jerking the weight"], back=True, areas=("back", "arms")),
        E("backpack_row", "One-arm backpack row",
          ["One hand on a chair seat, the other holding a loaded backpack.", "Pull the backpack toward the hip, elbow close to the body.", "Lower slowly; switch sides."],
          ["Twisting the trunk to lift"], back=True, areas=("back", "arms")),
        E("prone_ytw", "Floor Y raise",
          ["Lie face down, arms overhead in a Y, thumbs up.", "Lift both arms a little off the floor, hold a second, lower.",
           "Keep the neck long, eyes to the floor."],
          ["Lifting the head", "Swinging"], floor=True, areas=("back", "shoulders")),
    ],
    "lunge": [
        E("step_up_rail", "Step-up on the bottom stair, holding the rail",
          ["Hold the rail, place one foot on the bottom step.", "Press through that foot to step up; step down with control.", "Do all reps, then switch legs."],
          ["Pushing off the bottom foot", "Knee caving in"], knees=True, clip="", areas=("legs", "glutes")),
        E("supported_lunge", "Reverse lunge holding a chair",
          ["Stand beside a chair, one hand on its back.", "Step one foot back and lower both knees a little.", "Push through the front foot to return."],
          ["Front knee shooting forward past the toes", "Leaning the trunk"], knees=True, areas=("legs", "glutes")),
        E("reverse_lunge", "Reverse lunge",
          ["Stand tall, step one foot back.", "Lower until both knees are bent at about 90 degrees.", "Drive through the front heel to stand."],
          ["Losing balance: hold a chair", "Knee banging the floor"], knees=True, balance=True, areas=("legs", "glutes")),
        E("split_squat", "Split squat, slow",
          ["Feet in a long stride, back heel up.", "Lower straight down for three seconds, then press up.", "All reps on one side, then switch."],
          ["Front heel lifting"], knees=True, balance=True, areas=("legs", "glutes")),
    ],
    "core": [
        E("standing_march", "Standing march, tall posture",
          ["Stand tall, a hand on a counter if needed.", "Lift one knee to hip height, lower, switch.", "Brace the belly gently, as if about to be poked."],
          ["Leaning back", "Holding the breath"], areas=("core",)),
        E("wall_plank", "Wall plank",
          ["Hands on the wall at shoulder height, arms straight, step the feet back until the body leans in a straight "
           "line.", "Hold, breathing normally."],
          ["Hips sagging", "Holding the breath: count out loud"], hold=True, areas=("core", "shoulders")),
        E("dead_bug", "Dead bug",
          ["Lie on your back, arms up, knees bent over the hips.", "Lower one arm and the opposite leg slowly, lower back pressed down.",
           "Return and switch."],
          ["Lower back arching off the floor", "Moving too fast"], floor=True, areas=("core",)),
        E("bird_dog", "Bird dog",
          ["On hands and knees, back flat.", "Reach one arm forward and the opposite leg back.", "Hold a second, return, switch."],
          ["Twisting the hips", "Arching the back"], floor=True, balance=True, areas=("core", "back", "glutes")),
        E("plank", "Forearm plank",
          ["Forearms on the floor, elbows under the shoulders, legs straight.", "Hold a straight line from head to heels, breathing normally."],
          ["Hips too high or sagging", "Holding the breath"], floor=True, hold=True, shoulders=True, areas=("core", "shoulders")),
    ],
    "calf": [
        E("calf_raise_supported", "Calf raise holding a chair",
          ["One hand on the back of a sturdy chair, feet hip-width.", "Rise onto the balls of the feet, pause, lower slowly."],
          ["Rolling onto the outer edge of the foot"], clip="calf_raise", areas=("legs",)),
        E("calf_raise", "Standing calf raise",
          ["Feet hip-width, arms relaxed.", "Rise up high, pause one second, lower in two seconds."],
          ["Bouncing"], balance=True, clip="calf_raise_free", areas=("legs",)),
        E("single_calf_raise", "Single-leg calf raise",
          ["One foot lifted, a fingertip on the wall for balance.", "Rise and lower slowly; switch legs."],
          ["Bending the knee to help"], balance=True, areas=("legs",)),
    ],
    "balance": [
        E("tandem_stand", "Heel-to-toe stand at the counter",
          ["Stand by a counter, one foot directly in front of the other.", "Hold, eyes forward; hands hover over the counter, ready.", "Switch feet."],
          ["Looking down at the feet"], hold=True, balance=True, areas=("legs", "core")),
        E("single_leg_stand", "Single-leg stand at the counter",
          ["Hand near the counter, lift one foot a little.", "Hold, standing tall; switch legs."],
          ["Locking the standing knee"], hold=True, balance=True, areas=("legs", "core")),
        E("heel_toe_walk", "Heel-to-toe walk along a wall",
          ["Walk along a wall, placing each heel right in front of the other toes.", "Ten steps, turn, come back."],
          ["Rushing"], balance=True, areas=("legs", "core")),
    ],
}

WARM_UP = [  # what, how much, its clip
    ("March in place, swinging the arms", "2 minutes", "march_arms"),
    ("Arm circles, forward and back", "10 each way", "arm_circles"),
    ("Hip circles, hands on hips", "10 each way", "hip_circles"),
    ("Easy sit-to-stands or half squats", "8", "sit_to_stand"),
]
COOL_DOWN = [
    ("Calf stretch against the wall", "30 seconds each leg", "calf_stretch_wall"),
    ("Hamstring stretch: sit on a chair edge, one leg straight, lean forward with a flat back", "30 seconds each leg",
     "hamstring_chair"),
    ("Chest stretch in a doorway, hand on the frame, arm straight at shoulder height", "30 seconds each side",
     "chest_doorway"),
    ("Slow breathing: in through the nose for 4, out for 6", "1 minute", ""),
]


# Positions held or movements without a start and an end (balance, circles, marching, stretches): Veo could not show
# them right even from checked first and last frames (11 Nov, 1 of 10), so they get the checked photo of the position
PHOTOS = {"march_arms", "standing_march", "arm_circles", "hip_circles", "single_leg_stand", "heel_toe_walk",
          "tandem_stand", "calf_stretch_wall", "chest_doorway"}


# Repetitions Veo got wrong twice: the checked start and end positions, shown one after the other
PAIRS = {"wall_pushup", "knee_pushup", "backpack_row", "wall_w", "calf_raise", "single_calf_raise"}


def media(clip: str) -> dict | None:
    """What the page shows for a clip name: a looping video, the start and end positions alternating, or the photo."""
    if not clip:
        return None
    if clip in PAIRS:
        return {"kind": "pair", "src": [f"/static/exercises/{clip}_1.jpg", f"/static/exercises/{clip}_2.jpg"]}
    if clip in PHOTOS:
        return {"kind": "photo", "src": f"/static/exercises/{clip}.jpg"}
    return {"kind": "video", "src": f"/static/exercises/{clip}.mp4"}


def all_exercises() -> dict[str, Exercise]:
    return {e.id: e for ladder in LADDERS.values() for e in ladder}
