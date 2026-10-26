export interface Developer {
  name: string;
  /** The agents and parts of the system this person owned. */
  work: string;
  email: string;
  /** LinkedIn profile slug (linkedin.com/in/<slug>). */
  linkedin: string;
  /** GitHub username. */
  github: string;
}

export const DEVELOPERS: Developer[] = [
  {
    name: "Anjali Dinesh Jayashree More",
    work: "Contract & Risk agent",
    email: "anjalidineshmore@gmail.com",
    linkedin: "anjalimore",
    github: "anjalidmore",
  },
  {
    name: "Vaidehi Jagdeep Sankaye",
    work: "Document & Vendor agent",
    email: "vjsankaye@gmail.com",
    linkedin: "vaidehi-sankaye-776a982b9",
    github: "vsank16",
  },
  {
    name: "Niraj Ravindra Sawant",
    work: "Approval & Inventory agent",
    email: "nirajsawant203@gmail.com",
    linkedin: "niraj-sawant10",
    github: "Niraj-82",
  },
  {
    name: "Anooj Vinayak Shete",
    work: "Notification, Auth and Assistant",
    email: "anoojshete@gmail.com",
    linkedin: "anoojshete",
    github: "anoojshete",
  },
];
