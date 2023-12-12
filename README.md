# 📽 openpilot Replay Clipper

*Here's a small openpilot bug clip*:

https://github.com/commaai/openpilot/assets/5363/97a6c767-9b67-4206-8ba7-b4030f08a8cd

Capture and develop clips of [openpilot][op] from comma.ai's [Comma Connect](https://connect.comma.ai/).

The clipper can produce clips of:

* comma.ai openpilot UI (including desired path, lane lines, modes, etc.)
  * Origin of codebase, Segment ID, and seconds marker branded into the clip for debugging/reporting. Useful for posting clips in the [comma.ai Discord's #driving-feedback and/or #openpilot-experience channel](https://discord.comma.ai), [reddit](https://www.reddit.com/r/comma_ai), [Facebook](https://www.facebook.com/groups/706398630066928), or anywhere else that takes video. Very useful for [making outstanding bug reports](https://github.com/commaai/openpilot/wiki/FAQ#how-do-i-report-a-bug) as well as feedback on good behavior.
* Forward, Wide, and Driver Camera with no UI
  * Concatenate, cut, and convert the raw, low-compatibility, and separated HEVC files to one highly compatible H.264 MP4 for easy sharing.
* 360 Video
  * Rendered from Wide and Driver Camera. Uploadable to YouTube, viewable in VLC, and accepted by any video players or web services that take 360 videos.
* Forward Upon Wide and 360 Forward Upon Wide
  * Forward video is overlayed atop the wide video. Not perfect, but usable.

All clip options have a configurable target file size option as platforms like Discord limit file upload sizes.

The clipper is deployed on [Replicate](https://replicate.com):

https://replicate.com/nelsonjchen/op-replay-clipper

Replicate is an ultra-low-cost pay-as-you-go compute platform for running software jobs. Replicate is a great way to run this clipper as it's fast, easy to use, and you don't need to install anything on your computer or even deploy anything yourself. Just enter in the required information into the form, and Replicate will generate a clip. Expect to pay about ~$0.01 per clip but not even need to put in any payment details until you've reached a generously large level of usage.

## Terminology

* Route - A drive recorded by openpilot. Generally from Ignition On to Ignition Off.

## Requirements

- [comma.ai device](https://comma.ai/shop) that can upload to [comma Connect](https://connect.comma.ai).
- [Free GitHub](https://github.com) account to log into [Replicate](https://replicate.com) with

### Non-Requirements

- A comma lite or prime subscription.
   * Clipping was a comma connect prime-only feature but was removed for refurbishment. This is a free and open source tool to do the same.

## Quick Usage

We assume you've already paired your device and have access to the device with your comma connect account.

1. Visit [comma connect][connect] and select a route.
2. Scrub to the time you want to clip.
   * In this example, I've scrubbed to a time where I want to make a small clip of behind this cool car.
   * ![image](https://github.com/nelsonjchen/dutil/assets/5363/b37cba35-5ee1-4980-84bb-697c7306c99a)
3. Now I need to select the portion of the route I want to clip. Here's a video of what that UI looks like
   * See how I drag and select a portion.
   * You can see me make a mistake but pressing the left arrow (←) in the top-left corner lets me re-expand and try to trim again.
   * The clipper has a maximum length of 5 minutes. Try to select a portion that's less than that. Try to aim for 20 seconds to a minute though; everybody else has short attention spans.
   * Video:

     https://github.com/commaai/openpilot/assets/5363/504665de-9222-4e6b-b090-c26cdcc7137a
4. Once satisified with the selected portion, prepare the route and files for rendering.
   * Make sure all files are uploaded. Select "Upload All" under the "Files" dropdown if you haven't already and make sure it says `uploaded`. You may need to wait and your device may need to be on for a while for all files to upload.
      * The clipper only works with high-resolution files and needs all files that are part of the clip to be uploaded.
      * ![image](https://github.com/commaai/openpilot/assets/5363/ce997a7b-9a93-4f67-944b-95d09ae68b02)
   * Make sure the route has "Public access" under "More info" turned on. You can set this to off after you're done with clip making.
      * ![image](https://github.com/commaai/openpilot/assets/5363/6a55c181-d93f-4db5-9513-ff6a1d370757)
5. Copy the URL in the address bar to your clipboard. In the case above, I've copied "https://connect.comma.ai/fe18f736cb0d7813/1698203405863/1698203460702" to my clipboard.
   * When you were adjusting the selected portion of the route in the last step, it was changing those last two numbers in the URL which is the start time and end time respectively.
   * "Share This Route" button if it is present will work too. Choose "copy to clipboard" or similar.
6. Visit https://replicate.com/nelsonjchen/op-replay-clipper
7. Under `route`, paste the URL you copied in the previous step.
   * ![image](https://github.com/commaai/openpilot/assets/5363/15d286cc-057f-4a1c-be82-855c5b570b90)
8. Tweak any settings you like.
9. Press `Run`.
10. Wait for the clip to render. It may take a few minutes.
11. Once done, you can download the clip. If you want, turn off "Public access" on the route after you're done.
    * Here's a generated clip with the `wide` rendering type with no UI:

      https://github.com/commaai/openpilot/assets/5363/8bd91642-51ff-4de9-87d2-31e770c64542

## Gallery

Demonstration of speed or longitudinal behavior of openpilot with model-based longitudinal is nearly impossible or hard without this clipper. This video is of a good model based long behavior at highway speeds.

https://user-images.githubusercontent.com/5363/202886008-82cfbf02-d19a-4482-ab7a-59f96c802dd1.mp4

Cars can have bugs themselves. Here's my 2020 Corolla Hatchback phantomly braking on metal strips in stop and go traffic probably from the radar. Perhaps a future openpilot that doesn't depend on radar might be the one sanity checking the radar instead of the other way around currently. And another example of that in Portland.

https://user-images.githubusercontent.com/5363/219708673-4673f4ff-9b47-4c57-9be3-65f3ea703f3f.mp4

https://github.com/nelsonjchen/op-replay-clipper/assets/5363/1e59844b-46f8-4289-bea9-511db2718549

This is a video of a bug report where openpilot's lateral handling lost the lane.

https://user-images.githubusercontent.com/5363/205901777-53fd18f9-2ab5-400b-92f5-45daf3a34fbd.mp4

Lane cutting?

https://github.com/nelsonjchen/op-replay-clipper/assets/5363/d0ab3365-b5ef-4e05-84ee-370b88e8af02

Nav-assisted follow the road instead of taking the side road.

https://github.com/nelsonjchen/op-replay-clipper/assets/5363/8f970c76-21d1-4209-b0e1-3eb6989feea8

Copying the car in front to get around someone waiting for the left turn

https://github.com/nelsonjchen/op-replay-clipper/assets/5363/9f845b8d-e4aa-4ab3-8785-8d09b83c9d8b

## Limitations

- The UI replayed is comma.ai's latest stock UI on their master branch; routes from forks that differ alot from stock may not render correctly. Your experience may and will vary. Please make sure to note these replays are from fork data and may not be representative of the stock behavior. [The comma team really does not like it if you ask them to debug fork code as "it just takes too much time to be sidetracked by hidden and unclear changes"](https://discord.com/channels/469524606043160576/616456819027607567/1042263657851142194).

## Usage Tips

* Learn how to bookmark and flag interesting points on a drive/route.

  With the car on, soon after an incident when it is safe:
  1. Tap the screen to reveal a bookmark flag button if it isn't there already.
     * ![button_flag](https://github.com/nelsonjchen/op-replay-clipper/assets/5363/d0cf9372-78ad-4a06-9128-b6fdb6f5394c)
  2. Tap that icon.  
  3. This will result in small slivers of yellow in the timeline you can quickly hone in on. 
     * ![flagged](https://github.com/nelsonjchen/op-replay-clipper/assets/5363/15a3f611-ffb8-47de-b917-1988a0f6f66a)
  4. With regards to the clipper usage, during the process in which you are honing in on the start and of the clip, your upper bound of the clip will nearly all the time be at that yellow so your first or early drags to hone down should basically top out there and be very generous with the start time before the yellow.

## Advanced Usage

### JWT Token Input

There is a JWT Token input field.
This is for users who do not wish to set a route to be "Public access".
There is a major catch though.
The JWT Token is valid for 1 year and is irrevocable in any way.
Password changes from SSO account logins like in Comma Connect will not invalidate the token.
Addtionally, it is not granular, meaning it will give access to all routes for the user if leaked.

If you share a JWT Token with anyone, they will be able to access all your routes for 1 year with no possibility of revocation from you.
This is why it's not recommended to use this feature unless you know what you're doing compared to the "Public access" method which is much easier to revoke access to.

Tokens can be obtained from visiting https://jwt.comma.ai/ and logging in with the same comma connect account type. Tokens should be about 181 characters or longer.

### Replicate can queue up jobs to run in parallel

After you run something, just use your browser to "Duplicate" the tab, change the settings for the next thing, and press Run. Replicate will queue up jobs and if necessary, even scale up to run multiple jobs in parallel. Very cool!

## Credits

### UI

The real MVP is [@deanlee](https://github.com/deanlee) for the replay tool in the openpilot project. The level of effort to develop the replay tool is far beyond this script. The script is just a wrapper around the replay tool to make it easy to use for clipping videos.

https://github.com/commaai/openpilot/blame/master/tools/replay/main.cc

### Video-only

A lot of the FFmpeg commands is based off of [@ntegan1](https://github.com/ntegan1)'s research and documentation including a small disclosure of some but not all details by [@incognitojam](https://github.com/incognitojam) when [@incognitojam](https://github.com/incognitojam) was at comma.

https://discord.com/channels/469524606043160576/819046761287909446/1068406169317675078

[@morrislee](https://github.com/morrislee) provided original data suitable to try to reverse engineer 360 clips.

[do]: https://www.digitalocean.com/
[op]: https://github.com/commaai/openpilot
[ghcs]: https://github.com/features/codespaces
[replicate]: https://replicate.com/nelsonjchen/op-replay-clipper
[connect]: https://connect.comma.ai/
