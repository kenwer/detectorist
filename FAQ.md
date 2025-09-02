## Frequently Asked Questions (FAQ)

### Troubleshooting

#### Q1: When starting teh app on macOS, how do I get past the  *Detectorist.app Not Opened* message?
**A:** macOS prevents unsigned apps, but you still can [open a apps from an unknown developers](https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unknown-developer-mh40616/mac). Here's how:

1. When you attempt to open the app, a warning like this appears where you have no option to open it anyways, so just select _Done_: 

    <img src="https://github.com/user-attachments/assets/10445639-3ef9-4483-b816-a9e4b3a8b3b1" width="40%" alt="Image">

1. Once you saw the warning dialog above, check out the _System Settings_ -> _Privacy & Security_ which has a new entry. Select _Open Anyway_:

    ![Image](https://github.com/user-attachments/assets/620ba84f-0f4f-494c-b141-9a960df521f0)


3. From the Finder open the Detectorist.app again, and you'll now see the option to open the application. Select _Open Anyway_:

    <img src="https://github.com/user-attachments/assets/5acf81b7-1f5c-4ab0-9d37-f68f85ee96b1" width="40%" alt="Image">

4. Authorize the action. From now on the application can be started like any other.

Background: For this open source application there's no valid Developer ID certificate the app could signed with. Hence you get a warning. Apple requires code signing for macOS apps to verify their integrity and origin. The Apple Developer Program membership, which provides signing certificates, [costs $99 annually](https://developer.apple.com/support/compare-memberships/).
